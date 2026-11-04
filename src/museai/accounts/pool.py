"""Account pool: scheduling, per-account concurrency limits, health state and failover.

Usage::

    async with pool.lease(exclude={...}, hint=conversation_key) as lease:
        ... use lease.account ...
        lease.fail(exc)   # optional; success is recorded automatically otherwise
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import time
from collections import defaultdict
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from typing import Protocol

from ..errors import (
    NoAccountAvailable,
    UpstreamAuthError,
    UpstreamQuotaError,
    UpstreamTimeout,
)
from .model import Account, AccountStatus
from .store import AccountStore

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- strategies
class Strategy(Protocol):
    def choose(self, candidates: list[Account], hint: str | None) -> Account: ...


class RoundRobinStrategy:
    def __init__(self) -> None:
        self._counter = itertools.count()

    def choose(self, candidates: list[Account], hint: str | None) -> Account:
        ordered = sorted(candidates, key=lambda a: a.id)
        return ordered[next(self._counter) % len(ordered)]


class LRUStrategy:
    def choose(self, candidates: list[Account], hint: str | None) -> Account:
        return min(candidates, key=lambda a: a.last_used_at)


class AffinityStrategy:
    """Sticks a hint (e.g. conversation id / user id) to the account that served it last,
    so a driver can reuse warm browser tabs or upstream threads. Falls back to LRU."""

    def __init__(self, max_entries: int = 4096) -> None:
        self._map: dict[str, str] = {}
        self._max = max_entries
        self._fallback = LRUStrategy()

    def choose(self, candidates: list[Account], hint: str | None) -> Account:
        if hint and (acc_id := self._map.get(hint)):
            for acc in candidates:
                if acc.id == acc_id:
                    # Re-insert at the tail so a hot hint is never the one evicted.
                    self._map[hint] = self._map.pop(hint)
                    return acc
        acc = self._fallback.choose(candidates, hint)
        if hint:
            self._map.pop(hint, None)
            if len(self._map) >= self._max:
                # dicts keep insertion order, so the head is the coldest hint.
                self._map.pop(next(iter(self._map)))
            self._map[hint] = acc.id
        return acc


STRATEGIES: dict[str, type] = {
    "round_robin": RoundRobinStrategy,
    "lru": LRUStrategy,
    "affinity": AffinityStrategy,
}


# ---------------------------------------------------------------- lease
class Lease:
    def __init__(self, account: Account) -> None:
        self.account = account
        self.error: BaseException | None = None

    def fail(self, exc: BaseException) -> None:
        self.error = exc


# ---------------------------------------------------------------- pool
class AccountPool:
    def __init__(
        self,
        store: AccountStore,
        *,
        strategy: str = "lru",
        max_concurrency: int = 1,
        cooldown: float = 120.0,
        acquire_timeout: float = 60.0,
        persist_debounce: float = 1.0,
    ) -> None:
        self.store = store
        self.strategy: Strategy = STRATEGIES[strategy]()
        self.max_concurrency = max(1, max_concurrency)
        self.cooldown = cooldown
        self.acquire_timeout = acquire_timeout
        self.persist_debounce = max(0.0, persist_debounce)
        self._accounts: dict[str, Account] = {}
        self._inflight: dict[str, int] = defaultdict(int)
        self._cond = asyncio.Condition()
        self._dirty = False
        self._flush_task: asyncio.Task | None = None
        self._flush_lock = asyncio.Lock()

    # ---- lifecycle / CRUD ----
    async def load(self) -> None:
        self._accounts = {a.id: a for a in await self.store.load()}
        log.info("loaded %d account(s)", len(self._accounts))

    async def persist(self) -> None:
        """Mark state dirty and schedule a coalesced flush.

        Health counters change on every request, so writing the whole store
        per release turns each generation into an extra disk round-trip.
        Callers that need durability now should ``await flush()`` instead.
        """
        self._dirty = True
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._debounced_flush())

    async def _debounced_flush(self) -> None:
        try:
            await asyncio.sleep(self.persist_debounce)
        except asyncio.CancelledError:
            raise
        await self.flush()

    async def flush(self) -> None:
        """Write the current snapshot to disk immediately (no-op when clean)."""
        async with self._flush_lock:
            if not self._dirty:
                return
            self._dirty = False
            try:
                await self.store.save(list(self._accounts.values()))
            except BaseException:
                self._dirty = True
                raise

    async def shutdown(self) -> None:
        task, self._flush_task = self._flush_task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self.flush()

    def all(self) -> list[Account]:
        return list(self._accounts.values())

    def get(self, account_id: str) -> Account | None:
        return self._accounts.get(account_id)

    async def upsert(self, account: Account) -> Account:
        async with self._cond:
            self._accounts[account.id] = account
            self._cond.notify_all()
        self._dirty = True
        await self.flush()
        return account

    async def remove(self, account_id: str) -> bool:
        async with self._cond:
            removed = self._accounts.pop(account_id, None) is not None
        if removed:
            self._dirty = True
            await self.flush()
        return removed

    def stats(self) -> dict[str, int]:
        now = time.time()
        return {
            "total": len(self._accounts),
            "available": sum(1 for a in self._accounts.values() if a.is_available(now)),
            "invalid": sum(1 for a in self._accounts.values() if a.status == AccountStatus.INVALID),
            "inflight": sum(self._inflight.values()),
        }

    # ---- scheduling ----
    def _soonest_recovery(self) -> float | None:
        """Earliest wall-clock time a currently cooling account becomes usable again."""
        now = time.time()
        pending = [
            acc.cooldown_until
            for acc in self._accounts.values()
            if acc.enabled
            and acc.status == AccountStatus.COOLING
            and acc.cooldown_until > now
        ]
        return min(pending) if pending else None

    def _candidates(self, exclude: Iterable[str]) -> tuple[list[Account], bool]:
        """Returns (free candidates, whether any usable account is merely busy)."""
        now = time.time()
        excluded = set(exclude)
        horizon = now + self.acquire_timeout
        free, busy = [], False
        for acc in self._accounts.values():
            if acc.id in excluded:
                continue
            if acc.is_available(now):
                if self._inflight[acc.id] >= self.max_concurrency:
                    busy = True
                    continue
                free.append(acc)
                continue
            # Cooling down but back before we would give up: worth waiting for
            # instead of reporting the pool as empty.
            if acc.enabled and acc.status == AccountStatus.COOLING and now < acc.cooldown_until <= horizon:
                busy = True
        return free, busy

    async def acquire(self, *, exclude: Iterable[str] = (), hint: str | None = None) -> Account:
        exclude = tuple(exclude)
        deadline = time.monotonic() + self.acquire_timeout
        async with self._cond:
            while True:
                free, busy = self._candidates(exclude)
                if free:
                    acc = self.strategy.choose(free, hint)
                    self._inflight[acc.id] += 1
                    acc.last_used_at = time.time()
                    return acc
                if not busy:
                    raise NoAccountAvailable("no usable account in pool")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise NoAccountAvailable("all accounts are busy, try again later")
                wait = remaining
                recovery = self._soonest_recovery()
                if recovery is not None:
                    # No one notifies us when a cooldown elapses, so wake up then.
                    wait = min(wait, max(0.05, recovery - time.time()))
                try:
                    await asyncio.wait_for(self._cond.wait(), timeout=wait)
                except asyncio.TimeoutError:
                    continue

    async def release(self, account: Account, error: BaseException | None = None) -> None:
        async with self._cond:
            self._inflight[account.id] = max(0, self._inflight[account.id] - 1)
            self._apply_result(account, error)
            self._cond.notify_all()
        await self.persist()

    def _apply_result(self, acc: Account, error: BaseException | None) -> None:
        if error is None:
            acc.success_count += 1
            acc.last_error = None
            if acc.status == AccountStatus.COOLING:
                acc.status = AccountStatus.ACTIVE
            return
        acc.fail_count += 1
        acc.last_error = str(error)[:500]
        if isinstance(error, UpstreamAuthError):
            acc.status = AccountStatus.INVALID
            log.warning("account %s marked invalid: %s", acc.id, error)
        elif isinstance(error, UpstreamQuotaError):
            acc.status = AccountStatus.COOLING
            acc.cooldown_until = time.time() + max(self.cooldown, 3600)
            log.warning("account %s out of quota, cooling down", acc.id)
        elif isinstance(error, UpstreamTimeout):
            # A slow generation is upstream latency, not a dead account. Cooling
            # here would turn one late reply into minutes of zero capacity.
            log.warning("account %s timed out, staying active: %s", acc.id, error)
        elif getattr(error, "retryable", False):
            acc.status = AccountStatus.COOLING
            acc.cooldown_until = time.time() + self.cooldown

    @asynccontextmanager
    async def lease(
        self, *, exclude: Iterable[str] = (), hint: str | None = None
    ) -> AsyncIterator[Lease]:
        acc = await self.acquire(exclude=exclude, hint=hint)
        lease = Lease(acc)
        try:
            yield lease
        except (asyncio.CancelledError, GeneratorExit):
            # Client went away; not the account's fault.
            raise
        except BaseException as exc:
            lease.error = lease.error or exc
            raise
        finally:
            await self.release(acc, lease.error)

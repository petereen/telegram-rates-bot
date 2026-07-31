"""Dedicated, low-cost scheduler for actively used exchange rates."""

from __future__ import annotations

import asyncio
import logging

from config import REFRESH_WORKER_CONCURRENCY, REFRESH_WORKER_INTERVAL_SECONDS
from db.supabase_client import (
    get_all_active_rate_pairs,
    get_cached_rate_entry,
    release_rate_refresh_lease,
    set_cached_rate,
    try_acquire_rate_refresh_lease,
)
from providers.base import get_provider
from providers.registry import register_all_providers

log = logging.getLogger(__name__)


def _due_pairs() -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for provider_name, symbol in get_all_active_rate_pairs():
        try:
            provider = get_provider(provider_name)
            cached = get_cached_rate_entry(provider_name, symbol, include_stale=True)
            if cached and provider.is_fresh(cached[1]):
                continue
            grouped.setdefault(provider_name, []).append(symbol)
        except Exception as exc:
            log.warning("Cannot inspect refresh candidate %s/%s: %s", provider_name, symbol, exc)
    return grouped


def _refresh_provider(provider_name: str, symbols: list[str]) -> int:
    """Claim due symbols, then use one provider batch request when possible."""
    provider = get_provider(provider_name)
    claimed = [symbol for symbol in symbols if try_acquire_rate_refresh_lease(provider_name, symbol)]
    if not claimed:
        return 0
    try:
        payloads = provider.fetch_many(claimed)
        updated = 0
        for symbol in claimed:
            data = payloads.get(symbol, {"lines": [f"{provider_name} {symbol}: not found"]})
            if provider._cacheable(data, symbol):
                set_cached_rate(provider_name, symbol, data, next_refresh_at=provider.next_refresh_at())
                updated += 1
        return updated
    except Exception as exc:
        log.warning("Scheduled refresh failed for %s: %s", provider_name, exc)
        return 0
    finally:
        for symbol in claimed:
            try:
                release_rate_refresh_lease(provider_name, symbol)
            except Exception as exc:
                log.warning("Cannot release refresh lease %s/%s: %s", provider_name, symbol, exc)


async def refresh_active_rates_once() -> int:
    groups = await asyncio.to_thread(_due_pairs)
    semaphore = asyncio.Semaphore(REFRESH_WORKER_CONCURRENCY)

    async def refresh(name: str, symbols: list[str]) -> int:
        async with semaphore:
            return await asyncio.to_thread(_refresh_provider, name, symbols)

    results = await asyncio.gather(*(refresh(name, symbols) for name, symbols in groups.items()))
    return sum(results)


async def run() -> None:
    while True:
        try:
            updated = await refresh_active_rates_once()
            if updated:
                log.info("Scheduled refresh updated %d active rates", updated)
        except Exception:
            log.exception("Scheduled refresh iteration failed")
        await asyncio.sleep(REFRESH_WORKER_INTERVAL_SECONDS)


def main() -> None:
    logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
    register_all_providers()
    asyncio.run(run())


if __name__ == "__main__":
    main()

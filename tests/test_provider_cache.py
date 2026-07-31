import unittest
from datetime import datetime, timezone
from unittest.mock import ANY, patch

from db.supabase_client import _mem_cache, get_daily_cached_rate
from providers.base import BaseProvider


class DailyProvider(BaseProvider):
    NAME = "DailyTest"
    CACHE_DAILY = True
    PAIRS = {"USD/MNT": "USD"}
    FORMULA_FIELDS = {"USD/MNT": ("rate",)}

    def __init__(self, payload=None):
        self.payload = payload or {"rate": 3500, "lines": []}
        self.fetch_count = 0

    def fetch(self, symbol):
        self.fetch_count += 1
        return self.payload


class ProviderCacheTests(unittest.TestCase):
    def tearDown(self):
        _mem_cache.clear()

    def test_daily_cache_accepts_buy_sell_provider_payloads(self):
        payload = {"buy": 7.1, "sell": 7.2, "lines": []}
        _mem_cache[("BOC", "RUB")] = (datetime.now(timezone.utc), payload)

        self.assertEqual(get_daily_cached_rate("BOC", "RUB"), payload)

    def test_daily_provider_returns_today_cache_without_fetching(self):
        provider = DailyProvider()
        cached = {"rate": 3490, "lines": []}

        with patch(
            "providers.base.get_cached_rate_entry",
            return_value=(cached, datetime.now(timezone.utc)),
        ) as get_cached:
            self.assertEqual(provider.get_rate("USD/MNT"), cached)

        self.assertEqual(provider.fetch_count, 0)
        get_cached.assert_called_once_with("DailyTest", "USD/MNT", include_stale=True)

    def test_daily_provider_fetches_and_persists_successful_rate(self):
        provider = DailyProvider()

        with patch(
            "providers.base.get_cached_rate_entry", return_value=None
        ), patch("providers.base.try_acquire_rate_refresh_lease", return_value=True), patch(
            "providers.base.release_rate_refresh_lease"
        ), patch("providers.base.set_cached_rate") as set_cached:
            result = provider.get_rate("USD/MNT")

        self.assertEqual(result["rate"], 3500)
        self.assertEqual(provider.fetch_count, 1)
        set_cached.assert_called_once_with(
            "DailyTest", "USD/MNT", result, next_refresh_at=ANY
        )

    def test_daily_provider_does_not_cache_an_upstream_error(self):
        error = {"lines": ["DailyTest USD/MNT: fetch error"]}
        provider = DailyProvider(error)

        with patch(
            "providers.base.get_cached_rate_entry", return_value=None
        ), patch("providers.base.try_acquire_rate_refresh_lease", return_value=True), patch(
            "providers.base.release_rate_refresh_lease"
        ), patch("providers.base.set_cached_rate") as set_cached:
            self.assertEqual(provider.get_rate("USD/MNT"), error)

        set_cached.assert_not_called()

    def test_live_provider_keeps_using_short_ttl_cache(self):
        provider = DailyProvider()
        provider.CACHE_DAILY = False
        cached = {"rate": 3480, "lines": []}

        with patch(
            "providers.base.get_cached_rate_entry",
            return_value=(cached, datetime.now(timezone.utc)),
        ):
            self.assertEqual(provider.get_rate("USD/MNT"), cached)

        self.assertEqual(provider.fetch_count, 0)


if __name__ == "__main__":
    unittest.main()

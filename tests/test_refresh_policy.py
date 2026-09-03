import unittest
from datetime import datetime, timedelta, timezone

from providers.base import BaseProvider
from providers.xe import XEProvider


class PolicyProvider(BaseProvider):
    NAME = "PolicyTest"
    PAIRS = {"USD/MNT": "USD"}
    FORMULA_FIELDS = {"USD/MNT": ("rate",)}

    def fetch(self, symbol):
        return {"rate": 1, "lines": []}


class RefreshPolicyTests(unittest.TestCase):
    def test_live_and_hourly_expiry(self):
        now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
        provider = PolicyProvider()
        self.assertTrue(provider.is_fresh(now - timedelta(minutes=5), now))
        self.assertFalse(provider.is_fresh(now - timedelta(minutes=5, seconds=1), now))
        provider.REFRESH_POLICY = "hourly"
        self.assertTrue(provider.is_fresh(now - timedelta(minutes=59), now))
        self.assertFalse(provider.is_fresh(now - timedelta(hours=1, seconds=1), now))

    def test_daily_policy_uses_the_ub_refresh_window(self):
        provider = PolicyProvider()
        provider.CACHE_DAILY = True
        # 08:30 UB: yesterday's post-window result is still valid.
        now = datetime(2026, 1, 2, 0, 30, tzinfo=timezone.utc)
        self.assertTrue(provider.is_fresh(datetime(2026, 1, 1, 1, 1, tzinfo=timezone.utc), now))
        # 09:30 UB: the old snapshot is due for refresh.
        now = datetime(2026, 1, 2, 1, 30, tzinfo=timezone.utc)
        self.assertFalse(provider.is_fresh(datetime(2026, 1, 1, 1, 1, tzinfo=timezone.utc), now))

    def test_xe_refreshes_after_one_minute(self):
        provider = XEProvider()
        now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
        self.assertTrue(provider.is_fresh(now - timedelta(minutes=1), now))
        self.assertFalse(provider.is_fresh(now - timedelta(minutes=1, seconds=1), now))

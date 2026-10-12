import unittest

from pick_our_hike.route_facts import load_route_facts
from pick_our_hike.trip_context_loader import load_demo_snapshot


class SyntheticTripContextTests(unittest.TestCase):
    def test_context_covers_catalog_with_synthetic_weather(self):
        snapshot = load_demo_snapshot()
        self.assertEqual(snapshot["forecast_for_date"], "2026-10-11")
        self.assertEqual(set(snapshot["destinations"]), set(load_route_facts()))
        for item in snapshot["destinations"].values():
            self.assertEqual(item["weather"]["source_name"], "Invented demo scenario")
            self.assertNotIn("source_url", item["weather"])
            self.assertEqual(item["weather"]["forecast_for_date"], "2026-10-11")
            self.assertEqual(item["drive"]["basis"], "authored_demo_estimate_not_live_traffic")
            self.assertGreater(item["drive"]["outbound_miles"], 0)
            self.assertGreater(item["drive"]["outbound_minutes"], 0)
            self.assertNotIn("source_url", item["park_facts"])


if __name__ == "__main__":
    unittest.main()

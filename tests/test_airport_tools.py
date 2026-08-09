import json
import tempfile
import unittest
from pathlib import Path

from app.airport_tools import (
    analyze_sfo_demand_pressure,
    compare_lax_sna_congestion,
    get_anc_long_haul,
    list_capabilities,
    rank_new_england_airports,
)
from app.data_repository import AirportDataError, load_processed_json


class AirportToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.processed_dir = Path(self.temp_directory.name)

    def tearDown(self):
        self.temp_directory.cleanup()

    def write_json(self, filename: str, data: object) -> None:
        (self.processed_dir / filename).write_text(
            json.dumps(data), encoding="utf-8"
        )

    def test_missing_processed_file_has_actionable_error(self):
        with self.assertRaisesRegex(AirportDataError, "Run its data script first"):
            load_processed_json("missing.json", self.processed_dir)

    def test_get_anc_long_haul_returns_evidence(self):
        self.write_json(
            "t100_anc_long_haul.json",
            {
                "airport_code": "ANC",
                "period_start": "2025-05",
                "period_end": "2026-04",
                "definition": {"minimum_distance_miles": 3000},
                "all_scheduled_passenger_departures": 100,
                "long_haul_departures": 3,
                "long_haul_percentage": 3.0,
                "source": {"publisher": "BTS"},
                "assumptions": ["test assumption"],
            },
        )
        result = get_anc_long_haul(self.processed_dir)
        self.assertEqual(result["result"]["long_haul_percentage"], 3.0)
        self.assertEqual(result["definition"]["minimum_distance_miles"], 3000)

    def test_congestion_requires_both_airports(self):
        self.write_json(
            "lax_sna_congestion.json",
            {
                "period_start": "2025-05",
                "period_end": "2026-04",
                "airports": [
                    {
                        "airport_code": "LAX",
                        "scheduled_flights": 10,
                        "departure_delay_rate": 20,
                        "average_departure_delay_minutes": 15,
                        "average_taxi_out_minutes": 18,
                        "cancellation_rate": 1,
                        "diversion_rate": 0.2,
                        "delay_cause_mix": {},
                    }
                ],
                "source": {},
                "methodology": {},
                "scope_note": "proxy only",
            },
        )
        with self.assertRaisesRegex(ValueError, "missing SNA"):
            compare_lax_sna_congestion(self.processed_dir)

    def test_new_england_limit_is_validated_and_applied(self):
        ranking = [{"rank": index, "airport_code": f"A{index}"} for index in range(1, 9)]
        self.write_json(
            "new_england_ranking.json",
            {
                "current_period_start": "2025-05",
                "current_period_end": "2026-04",
                "comparison_period_start": "2024-05",
                "comparison_period_end": "2025-04",
                "ranking": ranking,
                "methodology": {},
                "scope": {},
                "source": {},
                "assumptions": [],
            },
        )
        result = rank_new_england_airports(3, self.processed_dir)
        self.assertEqual(len(result["candidates"]), 3)
        with self.assertRaisesRegex(ValueError, "between 1 and 8"):
            rank_new_england_airports(9, self.processed_dir)

    def test_sfo_rejects_direct_unmet_demand_claim(self):
        self.write_json(
            "sfo_demand_pressure.json",
            {
                "airport_code": "SFO",
                "comparison_period": "previous",
                "current_period": "current",
                "traffic": {},
                "scheduled_supply": {},
                "assessment": {
                    "direct_unmet_passenger_demand_measured": True
                },
                "source": {},
                "assumptions": [],
            },
        )
        with self.assertRaisesRegex(ValueError, "not measured"):
            analyze_sfo_demand_pressure(self.processed_dir)

    def test_capability_list_exposes_four_tools(self):
        capabilities = list_capabilities()
        self.assertEqual(len(capabilities), 4)
        self.assertEqual(
            {item["name"] for item in capabilities},
            {
                "get_anc_long_haul",
                "compare_lax_sna_congestion",
                "rank_new_england_airports",
                "analyze_sfo_demand_pressure",
            },
        )


if __name__ == "__main__":
    unittest.main()

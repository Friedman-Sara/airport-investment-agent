import unittest
from unittest.mock import patch

try:
    from scripts import fetch_new_england_ranking as ranking
except ModuleNotFoundError:
    import fetch_new_england_ranking as ranking


def make_row(code, year, month, passengers=80, seats=100, departures=1):
    return {
        "origin_airport_code": code,
        "origin_airport_name": f"Test Airport ({code})",
        "reporting_month": f"{year}-{month:02d}-01T00:00:00.000",
        "total_departures": str(departures),
        "total_passengers": str(passengers),
        "total_seats": str(seats),
    }


def complete_24_month_rows(code):
    rows = [
        make_row(code, 2024, month) for month in range(5, 13)
    ]
    rows.extend(make_row(code, 2025, month) for month in range(1, 13))
    rows.extend(make_row(code, 2026, month) for month in range(1, 5))
    return rows


class NewEnglandRankingTests(unittest.TestCase):
    def test_weighted_load_factor_uses_total_passengers_and_seats(self):
        rows = [
            make_row("PWM", 2025, 5, passengers=50, seats=100),
            make_row("PWM", 2025, 6, passengers=900, seats=1000),
        ]

        summary = ranking.summarize_period(rows)

        self.assertEqual(summary["passengers"], 950)
        self.assertEqual(summary["seats"], 1100)
        self.assertEqual(summary["weighted_load_factor"], 86.36)

    def test_percentile_rank_is_tie_aware(self):
        self.assertEqual(ranking.percentile_rank(2, [1, 2, 3]), 50.0)
        self.assertEqual(ranking.percentile_rank(2, [1, 2, 2, 3]), 50.0)

    def test_missing_month_is_rejected(self):
        rows = complete_24_month_rows("PWM")[:-1]

        with patch.object(ranking, "AIRPORT_CODES", ("PWM",)):
            with self.assertRaisesRegex(ValueError, "Missing PWM months: 2026-04"):
                ranking.build_airport_metrics(rows)

    def test_add_scores_ranks_stronger_metrics_first(self):
        metrics = []
        for code, load_factor, growth, passengers in [
            ("AAA", 90.0, 10.0, 1_000_000),
            ("BBB", 80.0, 5.0, 500_000),
            ("CCC", 70.0, 0.0, 100_000),
        ]:
            metrics.append(
                {
                    "airport_code": code,
                    "current_period": {
                        "weighted_load_factor": load_factor,
                        "passengers": passengers,
                    },
                    "passenger_growth_percentage": growth,
                }
            )

        scored = ranking.add_scores(metrics)

        self.assertEqual([airport["airport_code"] for airport in scored], ["AAA", "BBB", "CCC"])
        self.assertEqual(scored[0]["opportunity_score"], 100.0)
        self.assertEqual(scored[1]["opportunity_score"], 50.0)
        self.assertEqual(scored[2]["opportunity_score"], 0.0)


if __name__ == "__main__":
    unittest.main()

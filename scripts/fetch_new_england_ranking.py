"""Fetch BTS traffic data and rank scoped New England expansion candidates."""

import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


BASE_URL = "https://data.bts.gov/resource/r495-tyji.json"
DATASET_ID = "r495-tyji"

AIRPORT_CODES = ("BOS", "BDL", "PVD", "MHT", "PWM", "BTV", "ORH", "HVN")

PREVIOUS_PERIOD_START = (2024, 5)
PREVIOUS_PERIOD_END = (2025, 4)
CURRENT_PERIOD_START = (2025, 5)
CURRENT_PERIOD_END = (2026, 4)

RAW_OUTPUT = Path("data/raw/new_england_t100_raw.json")
PROCESSED_OUTPUT = Path("data/processed/new_england_ranking.json")

WEIGHTS = {
    "weighted_load_factor": 0.40,
    "passenger_growth": 0.40,
    "passenger_scale": 0.20,
}

SELECTED_FIELDS = [
    "origin_airport_code",
    "origin_airport_name",
    "reporting_month",
    "total_departures",
    "total_passengers",
    "total_seats",
]


def parse_period(reporting_month: str) -> tuple[int, int]:
    return int(reporting_month[:4]), int(reporting_month[5:7])


def is_between(
    value: tuple[int, int],
    start: tuple[int, int],
    end: tuple[int, int],
) -> bool:
    return start <= value <= end


def fetch_rows() -> tuple[list[dict], str]:
    airport_values = ",".join(f"'{code}'" for code in AIRPORT_CODES)
    query = {
        "$select": ",".join(SELECTED_FIELDS),
        "$where": (
            f"origin_airport_code in ({airport_values}) "
            "AND reporting_month >= '2024-05-01T00:00:00.000' "
            "AND reporting_month <= '2026-04-01T00:00:00.000'"
        ),
        "$order": "origin_airport_code,reporting_month",
        "$limit": "1000",
    }
    request_url = f"{BASE_URL}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(
        request_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "airport-investment-agent/0.1",
        },
    )

    print("Requesting New England traffic data from BTS...")
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response), request_url


def expected_months(
    start: tuple[int, int], end: tuple[int, int]
) -> set[tuple[int, int]]:
    months = set()
    year, month = start
    while (year, month) <= end:
        months.add((year, month))
        month += 1
        if month == 13:
            year += 1
            month = 1
    return months


def summarize_period(rows: list[dict]) -> dict:
    passengers = sum(int(row["total_passengers"]) for row in rows)
    seats = sum(int(row["total_seats"]) for row in rows)
    departures = sum(int(row["total_departures"]) for row in rows)
    load_factor = passengers / seats * 100 if seats else None

    return {
        "months": len(rows),
        "passengers": passengers,
        "seats": seats,
        "departures": departures,
        "weighted_load_factor": round(load_factor, 2) if load_factor is not None else None,
    }


def build_airport_metrics(rows: list[dict]) -> list[dict]:
    rows_by_airport = {code: [] for code in AIRPORT_CODES}
    for row in rows:
        code = row["origin_airport_code"]
        if code in rows_by_airport:
            rows_by_airport[code].append(row)

    previous_expected = expected_months(PREVIOUS_PERIOD_START, PREVIOUS_PERIOD_END)
    current_expected = expected_months(CURRENT_PERIOD_START, CURRENT_PERIOD_END)
    results = []

    for code in AIRPORT_CODES:
        airport_rows = rows_by_airport[code]
        months_found = {parse_period(row["reporting_month"]) for row in airport_rows}
        missing = (previous_expected | current_expected) - months_found
        if missing:
            missing_text = ", ".join(
                f"{year}-{month:02d}" for year, month in sorted(missing)
            )
            raise ValueError(f"Missing {code} months: {missing_text}")

        previous_rows = [
            row
            for row in airport_rows
            if is_between(
                parse_period(row["reporting_month"]),
                PREVIOUS_PERIOD_START,
                PREVIOUS_PERIOD_END,
            )
        ]
        current_rows = [
            row
            for row in airport_rows
            if is_between(
                parse_period(row["reporting_month"]),
                CURRENT_PERIOD_START,
                CURRENT_PERIOD_END,
            )
        ]

        previous = summarize_period(previous_rows)
        current = summarize_period(current_rows)
        if previous["passengers"] == 0:
            growth = None
        else:
            growth = (
                (current["passengers"] - previous["passengers"])
                / previous["passengers"]
                * 100
            )

        results.append(
            {
                "airport_code": code,
                "airport_name": airport_rows[0]["origin_airport_name"],
                "previous_period": previous,
                "current_period": current,
                "passenger_growth_percentage": (
                    round(growth, 2) if growth is not None else None
                ),
                "data_quality": "complete_24_months",
            }
        )

    return results


def percentile_rank(value: float, values: list[float]) -> float:
    """Return a tie-aware 0-100 percentile rank within the airport cohort."""
    if len(values) == 1:
        return 100.0

    lower = sum(candidate < value for candidate in values)
    equal = sum(candidate == value for candidate in values)
    average_zero_based_rank = lower + (equal - 1) / 2
    return round(average_zero_based_rank / (len(values) - 1) * 100, 2)


def add_scores(metrics: list[dict]) -> list[dict]:
    load_factors = [
        airport["current_period"]["weighted_load_factor"] for airport in metrics
    ]
    growth_values = [airport["passenger_growth_percentage"] for airport in metrics]
    log_passenger_values = [
        math.log10(max(airport["current_period"]["passengers"], 1))
        for airport in metrics
    ]

    for airport, log_passengers in zip(metrics, log_passenger_values):
        component_scores = {
            "weighted_load_factor": percentile_rank(
                airport["current_period"]["weighted_load_factor"], load_factors
            ),
            "passenger_growth": percentile_rank(
                airport["passenger_growth_percentage"], growth_values
            ),
            "passenger_scale": percentile_rank(
                log_passengers, log_passenger_values
            ),
        }
        total_score = sum(
            component_scores[component] * WEIGHTS[component]
            for component in WEIGHTS
        )
        airport["component_scores"] = component_scores
        airport["opportunity_score"] = round(total_score, 2)

    metrics.sort(key=lambda airport: airport["opportunity_score"], reverse=True)
    for rank, airport in enumerate(metrics, start=1):
        airport["rank"] = rank

    return metrics


def save_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def main() -> None:
    rows, request_url = fetch_rows()
    if not rows:
        raise ValueError("BTS returned no New England airport rows")

    metrics = build_airport_metrics(rows)
    ranking = add_scores(metrics)

    result = {
        "metric": "new_england_terminal_expansion_screening",
        "current_period_start": "2025-05",
        "current_period_end": "2026-04",
        "comparison_period_start": "2024-05",
        "comparison_period_end": "2025-04",
        "ranking": ranking,
        "methodology": {
            "score_range": "0-100 relative to the scoped New England cohort",
            "weights": WEIGHTS,
            "normalization": "Tie-aware percentile rank within the eight-airport cohort",
            "passenger_scale_transform": "log10 before percentile ranking",
        },
        "scope": {
            "included_airports": list(AIRPORT_CODES),
            "definition": (
                "Eight selected commercial airports covering all six New England states"
            ),
            "excluded": (
                "Smaller and strongly seasonal airports are outside the 24-hour MVP cohort"
            ),
        },
        "source": {
            "publisher": "U.S. Bureau of Transportation Statistics",
            "dataset": "T-100 Segment Summary By Origin Airport",
            "dataset_id": DATASET_ID,
            "access_method": "Public Socrata API",
            "request_url": request_url,
        },
        "assumptions": [
            "The score is a relative screening score, not investment profitability.",
            "Load factor is a demand-pressure proxy, not direct terminal utilization.",
            "Passenger growth compares two complete rolling 12-month periods.",
            "Passenger scale receives a smaller weight so BOS does not dominate solely by size.",
            "A high score requires analyst review and additional forecast and infrastructure data.",
        ],
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }

    save_json(RAW_OUTPUT, rows)
    save_json(PROCESSED_OUTPUT, result)

    print("\nNew England terminal-expansion screening ranking:")
    for airport in ranking:
        print(
            f"{airport['rank']}. {airport['airport_code']} "
            f"score={airport['opportunity_score']:.2f}, "
            f"growth={airport['passenger_growth_percentage']:.2f}%, "
            f"load factor={airport['current_period']['weighted_load_factor']:.2f}%"
        )

    print(f"\nSaved raw: {RAW_OUTPUT}")
    print(f"Saved processed: {PROCESSED_OUTPUT}")


if __name__ == "__main__":
    main()

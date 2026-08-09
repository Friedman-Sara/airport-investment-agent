"""Build a transparent SFO demand-pressure assessment from public BTS data.

The script intentionally does not claim that public BTS data directly measures
passengers who wanted to fly but could not. It combines two evidence layers:

1. Twenty-four months of BTS airport-summary API data for passenger, seat, and
   departure growth plus weighted load factor.
2. Existing T-100 Segment bulk files for scheduled versus performed passenger
   departures from SFO during May 2025-April 2026.

Output:
    data/processed/sfo_demand_pressure.json
"""

import csv
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


BASE_URL = "https://data.bts.gov/resource/r495-tyji.json"
DATASET_ID = "r495-tyji"
AIRPORT_CODE = "SFO"
PASSENGER_SERVICE_CLASS = "F"

PREVIOUS_PERIOD_START = (2024, 5)
PREVIOUS_PERIOD_END = (2025, 4)
CURRENT_PERIOD_START = (2025, 5)
CURRENT_PERIOD_END = (2026, 4)

ROUTE_INPUT_FILES = (
    Path("data/raw/t100_routes_2025_raw.csv"),
    Path("data/raw/t100_routes_2026_raw.csv"),
)
API_RAW_OUTPUT = Path("data/raw/sfo_t100_summary_raw.json")
PROCESSED_OUTPUT = Path("data/processed/sfo_demand_pressure.json")

SUMMARY_FIELDS = (
    "origin_airport_code",
    "origin_airport_name",
    "reporting_month",
    "total_departures",
    "total_passengers",
    "total_seats",
)

ROUTE_REQUIRED_FIELDS = {
    "DEPARTURES_SCHEDULED",
    "DEPARTURES_PERFORMED",
    "SEATS",
    "PASSENGERS",
    "ORIGIN",
    "YEAR",
    "MONTH",
    "CLASS",
}


def parse_period(reporting_month: str) -> tuple[int, int]:
    return int(reporting_month[:4]), int(reporting_month[5:7])


def is_between(
    value: tuple[int, int],
    start: tuple[int, int],
    end: tuple[int, int],
) -> bool:
    return start <= value <= end


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


def parse_decimal(
    value: str,
    field: str,
    source: Path,
    line_number: int,
) -> Decimal:
    try:
        return Decimal(value.strip())
    except (InvalidOperation, AttributeError) as error:
        raise ValueError(
            f"Invalid {field} value {value!r} in {source} at line {line_number}"
        ) from error


def decimal_to_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def percentage_change(current: int, previous: int) -> float | None:
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 2)


def fetch_summary_rows() -> tuple[list[dict], str]:
    query = {
        "$select": ",".join(SUMMARY_FIELDS),
        "$where": (
            "origin_airport_code = 'SFO' "
            "AND reporting_month >= '2024-05-01T00:00:00.000' "
            "AND reporting_month <= '2026-04-01T00:00:00.000'"
        ),
        "$order": "reporting_month",
        "$limit": "100",
    }
    request_url = f"{BASE_URL}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(
        request_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "airport-investment-agent/0.1",
        },
    )

    print("Requesting 24 months of SFO summary data from BTS...")
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response), request_url


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
        "weighted_load_factor": (
            round(load_factor, 2) if load_factor is not None else None
        ),
    }


def build_traffic_comparison(rows: list[dict]) -> dict:
    if not rows:
        raise ValueError("BTS returned no SFO summary rows")

    months_found = {parse_period(row["reporting_month"]) for row in rows}
    required = expected_months(
        PREVIOUS_PERIOD_START, PREVIOUS_PERIOD_END
    ) | expected_months(CURRENT_PERIOD_START, CURRENT_PERIOD_END)
    missing = required - months_found
    if missing:
        missing_text = ", ".join(
            f"{year}-{month:02d}" for year, month in sorted(missing)
        )
        raise ValueError(f"Missing SFO summary months: {missing_text}")

    previous_rows = [
        row
        for row in rows
        if is_between(
            parse_period(row["reporting_month"]),
            PREVIOUS_PERIOD_START,
            PREVIOUS_PERIOD_END,
        )
    ]
    current_rows = [
        row
        for row in rows
        if is_between(
            parse_period(row["reporting_month"]),
            CURRENT_PERIOD_START,
            CURRENT_PERIOD_END,
        )
    ]

    previous = summarize_period(previous_rows)
    current = summarize_period(current_rows)
    return {
        "previous_period": previous,
        "current_period": current,
        "changes": {
            "passenger_growth_percentage": percentage_change(
                current["passengers"], previous["passengers"]
            ),
            "seat_growth_percentage": percentage_change(
                current["seats"], previous["seats"]
            ),
            "departure_growth_percentage": percentage_change(
                current["departures"], previous["departures"]
            ),
            "load_factor_change_percentage_points": round(
                current["weighted_load_factor"]
                - previous["weighted_load_factor"],
                2,
            ),
        },
    }


def validate_route_header(fieldnames: list[str] | None, source: Path) -> None:
    if not fieldnames:
        raise ValueError(f"CSV file has no header: {source}")
    missing = ROUTE_REQUIRED_FIELDS - set(fieldnames)
    if missing:
        raise ValueError(
            f"Missing required fields in {source}: {', '.join(sorted(missing))}"
        )


def build_route_supply_metrics(input_files: tuple[Path, ...]) -> dict:
    scheduled = Decimal("0")
    performed = Decimal("0")
    positive_shortfall = Decimal("0")
    extra_performed = Decimal("0")
    estimated_unoperated_seats = Decimal("0")
    rows_without_seat_estimate = 0
    matching_rows = 0
    months_found: set[tuple[int, int]] = set()

    for source in input_files:
        if not source.exists():
            raise FileNotFoundError(f"Input file not found: {source}")

        print(f"Processing SFO route supply from {source}...")
        with source.open("r", encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            validate_route_header(reader.fieldnames, source)

            for line_number, row in enumerate(reader, start=2):
                year = int(parse_decimal(row["YEAR"], "YEAR", source, line_number))
                month = int(
                    parse_decimal(row["MONTH"], "MONTH", source, line_number)
                )
                period = (year, month)
                if not is_between(period, CURRENT_PERIOD_START, CURRENT_PERIOD_END):
                    continue
                if row["ORIGIN"].strip().upper() != AIRPORT_CODE:
                    continue
                if row["CLASS"].strip().upper() != PASSENGER_SERVICE_CLASS:
                    continue

                row_scheduled = parse_decimal(
                    row["DEPARTURES_SCHEDULED"],
                    "DEPARTURES_SCHEDULED",
                    source,
                    line_number,
                )
                row_performed = parse_decimal(
                    row["DEPARTURES_PERFORMED"],
                    "DEPARTURES_PERFORMED",
                    source,
                    line_number,
                )
                row_seats = parse_decimal(
                    row["SEATS"], "SEATS", source, line_number
                )

                matching_rows += 1
                months_found.add(period)
                scheduled += row_scheduled
                performed += row_performed

                difference = row_scheduled - row_performed
                if difference > 0:
                    positive_shortfall += difference
                    if row_performed > 0:
                        estimated_unoperated_seats += (
                            difference * row_seats / row_performed
                        )
                    else:
                        rows_without_seat_estimate += 1
                elif difference < 0:
                    extra_performed += -difference

    missing = expected_months(CURRENT_PERIOD_START, CURRENT_PERIOD_END) - months_found
    if missing:
        missing_text = ", ".join(
            f"{year}-{month:02d}" for year, month in sorted(missing)
        )
        raise ValueError(f"Missing SFO route months: {missing_text}")
    if scheduled <= 0:
        raise ValueError("No scheduled SFO passenger departures found")

    return {
        "months": len(months_found),
        "scheduled_departures": decimal_to_number(scheduled),
        "performed_departures": decimal_to_number(performed),
        "net_scheduled_minus_performed": decimal_to_number(scheduled - performed),
        "scheduled_departures_not_operated": decimal_to_number(
            positive_shortfall
        ),
        "departures_operated_above_reported_schedule": decimal_to_number(
            extra_performed
        ),
        "scheduled_service_shortfall_rate": round(
            float(positive_shortfall / scheduled * Decimal("100")), 2
        ),
        "estimated_seats_on_unoperated_scheduled_departures": round(
            float(estimated_unoperated_seats)
        ),
        "shortfall_rows_without_seat_estimate": rows_without_seat_estimate,
        "matching_source_rows": matching_rows,
    }


def build_assessment(traffic: dict, supply: dict) -> dict:
    current = traffic["current_period"]
    changes = traffic["changes"]
    load_factor_pressure = current["weighted_load_factor"] >= 80
    demand_outpaced_seat_growth = (
        changes["passenger_growth_percentage"]
        > changes["seat_growth_percentage"]
    )
    material_service_shortfall = (
        supply["scheduled_service_shortfall_rate"] >= 1
    )

    signals = {
        "load_factor_at_least_80_percent": load_factor_pressure,
        "passenger_growth_outpaced_seat_growth": demand_outpaced_seat_growth,
        "scheduled_service_shortfall_at_least_1_percent": (
            material_service_shortfall
        ),
    }
    signal_count = sum(signals.values())

    if signal_count == 3:
        level = "strong"
    elif signal_count >= 1:
        level = "moderate"
    else:
        level = "limited"

    return {
        "demand_pressure_level": level,
        "signals": signals,
        "direct_unmet_passenger_demand_measured": False,
        "measurable_supply_gap": (
            "Scheduled passenger departures reported but not performed"
        ),
        "interpretation": (
            "This is a deterministic screening assessment. It does not count "
            "people who wanted to fly but could not, and it does not prove "
            "that terminal expansion would be profitable."
        ),
    }


def save_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def main() -> None:
    summary_rows, request_url = fetch_summary_rows()
    traffic = build_traffic_comparison(summary_rows)
    supply = build_route_supply_metrics(ROUTE_INPUT_FILES)
    assessment = build_assessment(traffic, supply)

    result = {
        "airport_code": AIRPORT_CODE,
        "metric": "demand_pressure_and_scheduled_supply_gap",
        "comparison_period": "2024-05 through 2025-04",
        "current_period": "2025-05 through 2026-04",
        "traffic": traffic,
        "scheduled_supply": supply,
        "assessment": assessment,
        "source": {
            "publisher": "U.S. Bureau of Transportation Statistics",
            "summary_dataset": "T-100 Segment Summary By Origin Airport",
            "summary_dataset_id": DATASET_ID,
            "summary_access_method": "Public Socrata API",
            "summary_request_url": request_url,
            "route_dataset": "T-100 Segment (All Carriers)",
            "route_access_method": "Official public bulk download",
            "route_input_files": [str(path) for path in ROUTE_INPUT_FILES],
        },
        "assumptions": [
            "Public BTS data does not directly measure passengers unable to obtain a flight.",
            "Load factor, growth, and scheduled-service delivery are demand-pressure proxies.",
            "Only service class F is used for the scheduled passenger supply gap.",
            "Scheduled departures not performed are not identical to cancellations and may include reporting adjustments.",
            "Estimated unoperated seats use average seats per performed departure within each source row; rows with zero performed departures cannot be estimated.",
            "The result is an investment-screening signal, not a profitability calculation.",
        ],
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }

    save_json(API_RAW_OUTPUT, summary_rows)
    save_json(PROCESSED_OUTPUT, result)

    current = traffic["current_period"]
    changes = traffic["changes"]
    print("\nSFO demand-pressure assessment:")
    print(
        f"Passengers: {current['passengers']:,} "
        f"({changes['passenger_growth_percentage']:+.2f}% YoY)"
    )
    print(
        f"Seats: {current['seats']:,} "
        f"({changes['seat_growth_percentage']:+.2f}% YoY)"
    )
    print(f"Weighted load factor: {current['weighted_load_factor']:.2f}%")
    print(
        "Scheduled departures not operated: "
        f"{supply['scheduled_departures_not_operated']:,} "
        f"({supply['scheduled_service_shortfall_rate']:.2f}% of schedule)"
    )
    print(f"Demand-pressure level: {assessment['demand_pressure_level']}")
    print("Direct unmet passenger demand measured: no")
    print(f"\nSaved API raw: {API_RAW_OUTPUT}")
    print(f"Saved processed: {PROCESSED_OUTPUT}")


if __name__ == "__main__":
    main()

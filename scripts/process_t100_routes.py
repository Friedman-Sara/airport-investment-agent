"""Process BTS T-100 route files and calculate ANC long-haul share.

Input files:
    data/raw/t100_routes_2025_raw.csv
    data/raw/t100_routes_2026_raw.csv

Output file:
    data/processed/t100_anc_long_haul.json
"""

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


INPUT_FILES = (
    Path("data/raw/t100_routes_2025_raw.csv"),
    Path("data/raw/t100_routes_2026_raw.csv"),
)
OUTPUT_FILE = Path("data/processed/t100_anc_long_haul.json")

AIRPORT_CODE = "ANC"
PASSENGER_SERVICE_CLASS = "F"
LONG_HAUL_MIN_DISTANCE_MILES = Decimal("3000")
PERIOD_START = (2025, 5)
PERIOD_END = (2026, 4)

REQUIRED_FIELDS = {
    "DEPARTURES_PERFORMED",
    "SEATS",
    "PASSENGERS",
    "DISTANCE",
    "UNIQUE_CARRIER",
    "UNIQUE_CARRIER_NAME",
    "ORIGIN",
    "DEST",
    "DEST_CITY_NAME",
    "YEAR",
    "MONTH",
    "CLASS",
}


def is_in_period(year: int, month: int) -> bool:
    """Return True when the row is inside May 2025-April 2026."""
    return PERIOD_START <= (year, month) <= PERIOD_END


def expected_months() -> set[tuple[int, int]]:
    return {
        (2025, month) for month in range(5, 13)
    } | {
        (2026, month) for month in range(1, 5)
    }


def parse_integer(value: str, field: str, source: Path, line_number: int) -> int:
    try:
        return int(Decimal(value.strip()))
    except (InvalidOperation, ValueError, AttributeError) as error:
        raise ValueError(
            f"Invalid {field} value {value!r} in {source} at line {line_number}"
        ) from error


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


def decimal_to_json_number(value: Decimal) -> int | float:
    """Keep whole-number BTS values as integers in the JSON output."""
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def validate_header(fieldnames: list[str] | None, source: Path) -> None:
    if not fieldnames:
        raise ValueError(f"CSV file has no header: {source}")

    missing_fields = REQUIRED_FIELDS - set(fieldnames)
    if missing_fields:
        missing = ", ".join(sorted(missing_fields))
        raise ValueError(f"Missing required fields in {source}: {missing}")


def process_files() -> dict:
    total_departures = Decimal("0")
    long_haul_departures = Decimal("0")
    total_passengers = Decimal("0")
    long_haul_passengers = Decimal("0")
    matching_rows = 0
    months_found: set[tuple[int, int]] = set()

    route_totals: dict[str, dict] = defaultdict(
        lambda: {
            "destination_city": "",
            "distance_miles": Decimal("0"),
            "departures_performed": Decimal("0"),
            "passengers": Decimal("0"),
        }
    )

    for source in INPUT_FILES:
        if not source.exists():
            raise FileNotFoundError(f"Input file not found: {source}")

        print(f"Processing {source}...")

        with source.open("r", encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            validate_header(reader.fieldnames, source)

            for line_number, row in enumerate(reader, start=2):
                year = parse_integer(row["YEAR"], "YEAR", source, line_number)
                month = parse_integer(row["MONTH"], "MONTH", source, line_number)

                if not is_in_period(year, month):
                    continue
                if row["ORIGIN"].strip().upper() != AIRPORT_CODE:
                    continue
                if row["CLASS"].strip().upper() != PASSENGER_SERVICE_CLASS:
                    continue

                departures = parse_decimal(
                    row["DEPARTURES_PERFORMED"],
                    "DEPARTURES_PERFORMED",
                    source,
                    line_number,
                )

                # Rows with no performed flights do not affect the percentage.
                if departures <= 0:
                    continue

                distance = parse_decimal(
                    row["DISTANCE"], "DISTANCE", source, line_number
                )
                passengers = parse_decimal(
                    row["PASSENGERS"], "PASSENGERS", source, line_number
                )

                matching_rows += 1
                months_found.add((year, month))
                total_departures += departures
                total_passengers += passengers

                if distance < LONG_HAUL_MIN_DISTANCE_MILES:
                    continue

                long_haul_departures += departures
                long_haul_passengers += passengers

                destination = row["DEST"].strip().upper()
                route = route_totals[destination]
                route["destination_city"] = row["DEST_CITY_NAME"].strip()
                route["distance_miles"] = max(route["distance_miles"], distance)
                route["departures_performed"] += departures
                route["passengers"] += passengers

    missing_months = expected_months() - months_found
    if missing_months:
        formatted_months = ", ".join(
            f"{year}-{month:02d}" for year, month in sorted(missing_months)
        )
        raise ValueError(
            "The ANC scheduled-passenger data does not cover all 12 months. "
            f"Missing: {formatted_months}"
        )

    if total_departures == 0:
        raise ValueError("No performed ANC scheduled-passenger departures found")

    long_haul_percentage = (
        long_haul_departures / total_departures * Decimal("100")
    )

    routes = []
    for destination, values in route_totals.items():
        routes.append(
            {
                "destination": destination,
                "destination_city": values["destination_city"],
                "distance_miles": decimal_to_json_number(
                    values["distance_miles"]
                ),
                "departures_performed": decimal_to_json_number(
                    values["departures_performed"]
                ),
                "passengers": decimal_to_json_number(values["passengers"]),
            }
        )

    routes.sort(key=lambda route: route["departures_performed"], reverse=True)

    return {
        "airport_code": AIRPORT_CODE,
        "metric": "long_haul_departure_percentage",
        "period_start": "2025-05",
        "period_end": "2026-04",
        "months_returned": len(months_found),
        "definition": {
            "service_class": PASSENGER_SERVICE_CLASS,
            "service_class_description": "Scheduled passenger/cargo service",
            "minimum_distance_miles": int(LONG_HAUL_MIN_DISTANCE_MILES),
            "flight_weight": "DEPARTURES_PERFORMED",
        },
        "all_scheduled_passenger_departures": decimal_to_json_number(
            total_departures
        ),
        "long_haul_departures": decimal_to_json_number(long_haul_departures),
        "long_haul_percentage": round(float(long_haul_percentage), 2),
        "all_scheduled_passengers": decimal_to_json_number(total_passengers),
        "long_haul_passengers": decimal_to_json_number(long_haul_passengers),
        "matching_source_rows": matching_rows,
        "long_haul_routes": routes,
        "source": {
            "publisher": "U.S. Bureau of Transportation Statistics",
            "dataset": "T-100 Segment (All Carriers)",
            "input_files": [str(path) for path in INPUT_FILES],
            "access_method": "Official public bulk download",
        },
        "assumptions": [
            "Long-haul means a nonstop segment of at least 3,000 statute miles.",
            "Only service class F is included to exclude all-cargo and nonscheduled service.",
            "The percentage is weighted by performed departures, not CSV row count.",
            "This metric describes flight mix, not airport profitability by itself.",
        ],
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    result = process_files()

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\nANC long-haul result:")
    print(
        f"{result['long_haul_departures']:,} / "
        f"{result['all_scheduled_passenger_departures']:,} departures = "
        f"{result['long_haul_percentage']:.2f}%"
    )
    print(f"Months covered: {result['months_returned']}")
    print(f"Saved: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

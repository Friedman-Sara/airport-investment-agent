"""Fetch BTS on-time data and summarize LAX/SNA operational congestion.

The script downloads twelve official monthly ZIP files, keeps only rows whose
origin is LAX or SNA, and writes both filtered raw evidence and a deterministic
summary for May 2025 through April 2026.
"""

import csv
import io
import json
import shutil
import tempfile
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


BASE_URL = (
    "https://transtats.bts.gov/PREZIP/"
    "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_"
    "{year}_{month}.zip"
)

AIRPORT_CODES = ("LAX", "SNA")
MONTHS = (
    *((2025, month) for month in range(5, 13)),
    *((2026, month) for month in range(1, 5)),
)

RAW_OUTPUT = Path("data/raw/on_time_lax_sna_raw.csv")
PROCESSED_OUTPUT = Path("data/processed/lax_sna_congestion.json")

SELECTED_FIELDS = [
    "Year",
    "Month",
    "FlightDate",
    "Reporting_Airline",
    "Origin",
    "Dest",
    "Flights",
    "DepDel15",
    "DepDelayMinutes",
    "TaxiOut",
    "Cancelled",
    "Diverted",
    "CarrierDelay",
    "WeatherDelay",
    "NASDelay",
    "SecurityDelay",
    "LateAircraftDelay",
]

REQUIRED_FIELDS = set(SELECTED_FIELDS)
CAUSE_FIELDS = (
    "CarrierDelay",
    "WeatherDelay",
    "NASDelay",
    "SecurityDelay",
    "LateAircraftDelay",
)


def parse_optional_decimal(value: str | None) -> Decimal | None:
    if value is None or not value.strip():
        return None

    try:
        return Decimal(value.strip())
    except InvalidOperation as error:
        raise ValueError(f"Invalid numeric value: {value!r}") from error


def decimal_to_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def percentage(numerator: Decimal, denominator: Decimal) -> float | None:
    if denominator == 0:
        return None
    return round(float(numerator / denominator * Decimal("100")), 2)


def average(total: Decimal, observations: Decimal) -> float | None:
    if observations == 0:
        return None
    return round(float(total / observations), 2)


def empty_metrics() -> dict:
    return {
        "scheduled_flights": Decimal("0"),
        "cancelled_flights": Decimal("0"),
        "diverted_flights": Decimal("0"),
        "delay_eligible_flights": Decimal("0"),
        "delayed_15_flights": Decimal("0"),
        "departure_delay_minutes": Decimal("0"),
        "departure_delay_observations": Decimal("0"),
        "taxi_out_minutes": Decimal("0"),
        "taxi_out_observations": Decimal("0"),
        "cause_minutes": defaultdict(lambda: Decimal("0")),
        "months": set(),
        "raw_rows": 0,
    }


def download_month(year: int, month: int, destination: Path) -> str:
    url = BASE_URL.format(year=year, month=month)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "airport-investment-agent/0.1",
            "Accept": "application/zip",
        },
    )

    print(f"Downloading {year}-{month:02d}...")
    with urllib.request.urlopen(request, timeout=120) as response:
        with destination.open("wb") as output_file:
            shutil.copyfileobj(response, output_file)

    return url


def validate_header(fieldnames: list[str] | None, source_name: str) -> None:
    if not fieldnames:
        raise ValueError(f"CSV file has no header: {source_name}")

    missing = REQUIRED_FIELDS - set(fieldnames)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(f"Missing required fields in {source_name}: {missing_text}")


def process_row(row: dict[str, str], metrics: dict) -> None:
    flights = parse_optional_decimal(row["Flights"]) or Decimal("1")
    cancelled = parse_optional_decimal(row["Cancelled"]) or Decimal("0")
    diverted = parse_optional_decimal(row["Diverted"]) or Decimal("0")

    metrics["scheduled_flights"] += flights
    metrics["cancelled_flights"] += cancelled
    metrics["diverted_flights"] += diverted
    metrics["raw_rows"] += 1
    metrics["months"].add((int(row["Year"]), int(row["Month"])))

    dep_del_15 = parse_optional_decimal(row["DepDel15"])
    if dep_del_15 is not None:
        metrics["delay_eligible_flights"] += flights
        metrics["delayed_15_flights"] += dep_del_15

    dep_delay_minutes = parse_optional_decimal(row["DepDelayMinutes"])
    if dep_delay_minutes is not None:
        metrics["departure_delay_minutes"] += dep_delay_minutes
        metrics["departure_delay_observations"] += flights

    taxi_out = parse_optional_decimal(row["TaxiOut"])
    if taxi_out is not None:
        metrics["taxi_out_minutes"] += taxi_out
        metrics["taxi_out_observations"] += flights

    for field in CAUSE_FIELDS:
        cause_minutes = parse_optional_decimal(row[field])
        if cause_minutes is not None:
            metrics["cause_minutes"][field] += cause_minutes


def build_airport_summary(airport_code: str, metrics: dict) -> dict:
    expected_months = set(MONTHS)
    missing_months = expected_months - metrics["months"]
    if missing_months:
        missing_text = ", ".join(
            f"{year}-{month:02d}" for year, month in sorted(missing_months)
        )
        raise ValueError(f"Missing {airport_code} months: {missing_text}")

    operated_flights = (
        metrics["scheduled_flights"] - metrics["cancelled_flights"]
    )
    total_cause_minutes = sum(
        metrics["cause_minutes"].values(),
        start=Decimal("0"),
    )

    cause_mix = {}
    for field in CAUSE_FIELDS:
        minutes = metrics["cause_minutes"][field]
        cause_mix[field] = {
            "minutes": decimal_to_number(minutes),
            "percentage": percentage(minutes, total_cause_minutes),
        }

    return {
        "airport_code": airport_code,
        "months_returned": len(metrics["months"]),
        "scheduled_flights": decimal_to_number(metrics["scheduled_flights"]),
        "operated_flights": decimal_to_number(operated_flights),
        "delayed_15_flights": decimal_to_number(metrics["delayed_15_flights"]),
        "departure_delay_rate": percentage(
            metrics["delayed_15_flights"],
            metrics["delay_eligible_flights"],
        ),
        "average_departure_delay_minutes": average(
            metrics["departure_delay_minutes"],
            metrics["departure_delay_observations"],
        ),
        "average_taxi_out_minutes": average(
            metrics["taxi_out_minutes"],
            metrics["taxi_out_observations"],
        ),
        "cancelled_flights": decimal_to_number(metrics["cancelled_flights"]),
        "cancellation_rate": percentage(
            metrics["cancelled_flights"],
            metrics["scheduled_flights"],
        ),
        "diverted_flights": decimal_to_number(metrics["diverted_flights"]),
        "diversion_rate": percentage(
            metrics["diverted_flights"],
            metrics["scheduled_flights"],
        ),
        "delay_cause_mix": cause_mix,
        "filtered_raw_rows": metrics["raw_rows"],
    }


def fetch_and_process() -> dict:
    metrics_by_airport = {
        airport_code: empty_metrics() for airport_code in AIRPORT_CODES
    }
    source_urls = []

    RAW_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    raw_part_file = RAW_OUTPUT.with_suffix(".csv.part")

    try:
        with raw_part_file.open(
            "w", encoding="utf-8", newline=""
        ) as filtered_file:
            writer = csv.DictWriter(filtered_file, fieldnames=SELECTED_FIELDS)
            writer.writeheader()

            for year, month in MONTHS:
                with tempfile.TemporaryDirectory() as temp_directory:
                    zip_path = Path(temp_directory) / f"on_time_{year}_{month}.zip"
                    source_urls.append(download_month(year, month, zip_path))

                    with zipfile.ZipFile(zip_path) as archive:
                        csv_names = [
                            name
                            for name in archive.namelist()
                            if name.lower().endswith(".csv")
                        ]
                        if not csv_names:
                            raise ValueError(f"No CSV found inside {zip_path.name}")

                        csv_name = csv_names[0]
                        with archive.open(csv_name) as binary_csv:
                            with io.TextIOWrapper(
                                binary_csv,
                                encoding="utf-8-sig",
                                newline="",
                            ) as text_csv:
                                reader = csv.DictReader(text_csv)
                                validate_header(reader.fieldnames, csv_name)

                                for row in reader:
                                    airport_code = row["Origin"].strip().upper()
                                    if airport_code not in AIRPORT_CODES:
                                        continue

                                    filtered_row = {
                                        field: row.get(field, "")
                                        for field in SELECTED_FIELDS
                                    }
                                    writer.writerow(filtered_row)
                                    process_row(
                                        filtered_row,
                                        metrics_by_airport[airport_code],
                                    )

        raw_part_file.replace(RAW_OUTPUT)
    except Exception:
        raw_part_file.unlink(missing_ok=True)
        raise

    airport_summaries = [
        build_airport_summary(airport_code, metrics_by_airport[airport_code])
        for airport_code in AIRPORT_CODES
    ]

    return {
        "metric": "operational_congestion_comparison",
        "period_start": "2025-05",
        "period_end": "2026-04",
        "airports": airport_summaries,
        "source": {
            "publisher": "U.S. Bureau of Transportation Statistics",
            "dataset": "Reporting Carrier On-Time Performance (1987-present)",
            "access_method": "Official public monthly bulk-download endpoint",
            "monthly_files": source_urls,
        },
        "methodology": {
            "departure_delay_rate": (
                "Flights delayed at least 15 minutes divided by flights with "
                "a reported departure-delay indicator"
            ),
            "cancellation_rate": (
                "Cancelled flights divided by scheduled flights"
            ),
            "average_departure_delay_minutes": (
                "Mean DepDelayMinutes over flights with a reported value; "
                "early departures are recorded as zero"
            ),
            "average_taxi_out_minutes": (
                "Mean TaxiOut over flights with a reported value"
            ),
            "delay_cause_mix": (
                "Each reported cause's minutes divided by total reported "
                "cause minutes"
            ),
        },
        "scope_note": (
            "These metrics are an operational congestion proxy. They do not "
            "directly measure terminal crowding or terminal capacity."
        ),
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    result = fetch_and_process()

    PROCESSED_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PROCESSED_OUTPUT.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\nOperational congestion metrics:")
    for airport in result["airports"]:
        print(
            f"{airport['airport_code']}: "
            f"delay rate={airport['departure_delay_rate']}%, "
            f"avg delay={airport['average_departure_delay_minutes']} min, "
            f"taxi-out={airport['average_taxi_out_minutes']} min, "
            f"cancellation rate={airport['cancellation_rate']}%"
        )

    print(f"\nSaved raw: {RAW_OUTPUT}")
    print(f"Saved processed: {PROCESSED_OUTPUT}")


if __name__ == "__main__":
    main()

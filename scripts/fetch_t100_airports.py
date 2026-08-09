import json
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path


BASE_URL = "https://data.bts.gov/resource/r495-tyji.json"

AIRPORT_CODES = ("LAX", "SNA", "ANC", "SFO")

SELECTED_FIELDS = [
    "origin_airport_code",
    "origin_airport_name",
    "reporting_month",
    "total_departures",
    "total_passengers",
    "total_seats",
    "total_load_factor",
]


def fetch_airport_data() -> list[dict]:
    airport_values = ",".join(
        f"'{airport_code}'" for airport_code in AIRPORT_CODES
    )

    query_parameters = {
        "$select": ",".join(SELECTED_FIELDS),
        "$where": (
            f"origin_airport_code in ({airport_values})"
        ),
        "$order": "reporting_month DESC",
        "$limit": "200",
    }

    query_string = urllib.parse.urlencode(query_parameters)
    request_url = f"{BASE_URL}?{query_string}"

    print("Requesting BTS data...")
    print(request_url)

    request = urllib.request.Request(
        request_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "airport-investment-agent/0.1",
        },
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def take_latest_12_months(rows: list[dict]) -> dict[str, list[dict]]:
    rows_by_airport = defaultdict(list)

    for row in rows:
        airport_code = row["origin_airport_code"]
        rows_by_airport[airport_code].append(row)

    latest_rows = {}

    for airport_code in AIRPORT_CODES:
        airport_rows = rows_by_airport.get(airport_code, [])

        airport_rows.sort(
            key=lambda row: row["reporting_month"],
            reverse=True,
        )

        latest_rows[airport_code] = airport_rows[:12]

    return latest_rows


def build_summary(
    rows_by_airport: dict[str, list[dict]],
) -> list[dict]:
    summaries = []

    for airport_code in AIRPORT_CODES:
        rows = rows_by_airport.get(airport_code, [])

        if not rows:
            summaries.append(
                {
                    "airport_code": airport_code,
                    "error": "No data returned",
                }
            )
            continue

        total_departures = sum(
            int(row.get("total_departures", 0))
            for row in rows
        )

        total_passengers = sum(
            int(row.get("total_passengers", 0))
            for row in rows
        )

        total_seats = sum(
            int(row.get("total_seats", 0))
            for row in rows
        )

        weighted_load_factor = (
            total_passengers / total_seats * 100
            if total_seats > 0
            else None
        )

        summaries.append(
            {
                "airport_code": airport_code,
                "airport_name": rows[0]["origin_airport_name"],
                "months_returned": len(rows),
                "period_start": rows[-1]["reporting_month"][:10],
                "period_end": rows[0]["reporting_month"][:10],
                "total_departures": total_departures,
                "total_passengers": total_passengers,
                "total_seats": total_seats,
                "weighted_load_factor": (
                    round(weighted_load_factor, 1)
                    if weighted_load_factor is not None
                    else None
                ),
            }
        )

    return summaries


def save_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    raw_rows = fetch_airport_data()
    latest_rows = take_latest_12_months(raw_rows)
    summaries = build_summary(latest_rows)

    save_json(
        Path("data/raw/t100_airports_raw.json"),
        raw_rows,
    )

    save_json(
        Path("data/processed/t100_airports_summary.json"),
        summaries,
    )

    print("\nAirport summaries:")

    for summary in summaries:
        print(json.dumps(summary, indent=2))

    print("\nSaved:")
    print("- data/raw/t100_airports_raw.json")
    print("- data/processed/t100_airports_summary.json")


if __name__ == "__main__":
    main()
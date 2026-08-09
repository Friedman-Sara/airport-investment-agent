import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

try:
    from scripts import process_t100_routes as processor
except ModuleNotFoundError:
    # Allows this standalone test artifact to be verified before it is copied
    # into the project's tests directory.
    import process_t100_routes as processor


CSV_FIELDS = [
    "DEPARTURES_SCHEDULED",
    "DEPARTURES_PERFORMED",
    "SEATS",
    "PASSENGERS",
    "DISTANCE",
    "UNIQUE_CARRIER",
    "UNIQUE_CARRIER_NAME",
    "ORIGIN_AIRPORT_ID",
    "ORIGIN",
    "DEST_AIRPORT_ID",
    "DEST",
    "DEST_CITY_NAME",
    "AIRCRAFT_TYPE",
    "YEAR",
    "MONTH",
    "CLASS",
]


def make_row(
    *,
    year,
    month,
    origin="ANC",
    destination="SEA",
    distance=1448,
    departures=1,
    passengers=100,
    service_class="F",
):
    return {
        "DEPARTURES_SCHEDULED": departures,
        "DEPARTURES_PERFORMED": departures,
        "SEATS": passengers + 20,
        "PASSENGERS": passengers,
        "DISTANCE": distance,
        "UNIQUE_CARRIER": "ZZ",
        "UNIQUE_CARRIER_NAME": "Test Airline",
        "ORIGIN_AIRPORT_ID": 10299,
        "ORIGIN": origin,
        "DEST_AIRPORT_ID": 14747,
        "DEST": destination,
        "DEST_CITY_NAME": "Test City",
        "AIRCRAFT_TYPE": 614,
        "YEAR": year,
        "MONTH": month,
        "CLASS": service_class,
    }


def twelve_month_rows():
    rows = [
        make_row(year=2025, month=month)
        for month in range(5, 13)
    ]
    rows.extend(
        make_row(year=2026, month=month)
        for month in range(1, 5)
    )
    return rows


def write_csv(path, rows, fields=CSV_FIELDS):
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class ProcessT100RoutesTests(unittest.TestCase):
    def test_is_in_period_boundaries(self):
        cases = [
            (2025, 4, False),
            (2025, 5, True),
            (2025, 12, True),
            (2026, 1, True),
            (2026, 4, True),
            (2026, 5, False),
        ]

        for year, month, expected in cases:
            with self.subTest(year=year, month=month):
                self.assertIs(processor.is_in_period(year, month), expected)

    def test_business_filters_and_departure_weighting(self):
        rows = twelve_month_rows()

        # Included in both numerator and denominator: exactly 3,000 miles.
        rows.append(
            make_row(
                year=2025,
                month=5,
                destination="DFW",
                distance=3000,
                departures=3,
                passengers=300,
            )
        )

        # Included only in denominator: below the long-haul threshold.
        rows.append(
            make_row(
                year=2025,
                month=5,
                destination="PDX",
                distance=2999,
                departures=7,
                passengers=700,
            )
        )

        # Excluded because it is cargo service.
        rows.append(
            make_row(
                year=2025,
                month=5,
                destination="FRA",
                distance=4500,
                departures=100,
                service_class="G",
            )
        )

        # Excluded because it is nonscheduled service.
        rows.append(
            make_row(
                year=2025,
                month=5,
                destination="HND",
                distance=3500,
                departures=100,
                service_class="L",
            )
        )

        # Excluded because the flight does not originate at ANC.
        rows.append(
            make_row(
                year=2025,
                month=5,
                origin="LAX",
                destination="JFK",
                distance=4000,
                departures=100,
            )
        )

        with TemporaryDirectory() as temp_directory:
            source = Path(temp_directory) / "routes.csv"
            write_csv(source, rows)

            with patch.object(processor, "INPUT_FILES", (source,)):
                result = processor.process_files()

        # Twelve baseline departures + 3 at threshold + 7 below threshold.
        self.assertEqual(result["all_scheduled_passenger_departures"], 22)
        self.assertEqual(result["long_haul_departures"], 3)
        self.assertEqual(result["long_haul_percentage"], 13.64)
        self.assertEqual(len(result["long_haul_routes"]), 1)
        self.assertEqual(result["long_haul_routes"][0]["destination"], "DFW")

    def test_rejects_incomplete_period(self):
        rows = [
            row
            for row in twelve_month_rows()
            if not (row["YEAR"] == 2026 and row["MONTH"] == 4)
        ]

        with TemporaryDirectory() as temp_directory:
            source = Path(temp_directory) / "missing_month.csv"
            write_csv(source, rows)

            with patch.object(processor, "INPUT_FILES", (source,)):
                with self.assertRaisesRegex(ValueError, "Missing: 2026-04"):
                    processor.process_files()

    def test_rejects_missing_required_column(self):
        fields_without_distance = [
            field for field in CSV_FIELDS if field != "DISTANCE"
        ]
        rows_without_distance = [
            {key: value for key, value in row.items() if key != "DISTANCE"}
            for row in twelve_month_rows()
        ]

        with TemporaryDirectory() as temp_directory:
            source = Path(temp_directory) / "missing_column.csv"
            write_csv(source, rows_without_distance, fields_without_distance)

            with patch.object(processor, "INPUT_FILES", (source,)):
                with self.assertRaisesRegex(ValueError, "DISTANCE"):
                    processor.process_files()


if __name__ == "__main__":
    unittest.main()

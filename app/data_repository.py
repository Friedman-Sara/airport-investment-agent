"""Read and minimally validate deterministic processed airport data."""

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"


class AirportDataError(RuntimeError):
    """Raised when processed airport evidence is missing or malformed."""


def load_processed_json(
    filename: str,
    processed_dir: Path | None = None,
) -> dict[str, Any]:
    """Load one known processed JSON artifact from the data directory."""
    directory = processed_dir or DEFAULT_PROCESSED_DIR
    path = directory / filename

    if not path.exists():
        raise AirportDataError(
            f"Processed data file not found: {path}. Run its data script first."
        )

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise AirportDataError(f"Invalid JSON in processed file: {path}") from error

    if not isinstance(data, dict):
        raise AirportDataError(f"Expected a JSON object in processed file: {path}")

    return data


def require_fields(
    data: dict[str, Any],
    fields: tuple[str, ...],
    context: str,
) -> None:
    """Reject processed data that does not match the expected contract."""
    missing = [field for field in fields if field not in data]
    if missing:
        raise AirportDataError(
            f"Missing required fields in {context}: {', '.join(missing)}"
        )

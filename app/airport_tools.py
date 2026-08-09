"""Deterministic read-only tools for the airport intelligence agent.

These functions contain no LLM calls. They expose stable, JSON-compatible
business results that can later be wrapped as LangChain tools or API endpoints.
"""

from pathlib import Path
from typing import Any

from app.data_repository import load_processed_json, require_fields


def get_anc_long_haul(processed_dir: Path | None = None) -> dict[str, Any]:
    """Return ANC long-haul flight share with definition and evidence."""
    data = load_processed_json("t100_anc_long_haul.json", processed_dir)
    require_fields(
        data,
        (
            "airport_code",
            "period_start",
            "period_end",
            "definition",
            "all_scheduled_passenger_departures",
            "long_haul_departures",
            "long_haul_percentage",
            "source",
            "assumptions",
        ),
        "ANC long-haul data",
    )

    return {
        "capability": "anc_long_haul",
        "airport_code": data["airport_code"],
        "period": {
            "start": data["period_start"],
            "end": data["period_end"],
        },
        "result": {
            "long_haul_departures": data["long_haul_departures"],
            "all_departures": data["all_scheduled_passenger_departures"],
            "long_haul_percentage": data["long_haul_percentage"],
        },
        "definition": data["definition"],
        "source": data["source"],
        "assumptions": data["assumptions"],
    }


def compare_lax_sna_congestion(
    processed_dir: Path | None = None,
) -> dict[str, Any]:
    """Return the deterministic LAX/SNA operational-congestion comparison."""
    data = load_processed_json("lax_sna_congestion.json", processed_dir)
    require_fields(
        data,
        (
            "period_start",
            "period_end",
            "airports",
            "source",
            "methodology",
            "scope_note",
        ),
        "LAX/SNA congestion data",
    )

    airports = {}
    for airport in data["airports"]:
        require_fields(
            airport,
            (
                "airport_code",
                "scheduled_flights",
                "departure_delay_rate",
                "average_departure_delay_minutes",
                "average_taxi_out_minutes",
                "cancellation_rate",
                "diversion_rate",
                "delay_cause_mix",
            ),
            "airport congestion entry",
        )
        airports[airport["airport_code"]] = airport

    for required_airport in ("LAX", "SNA"):
        if required_airport not in airports:
            raise ValueError(f"Congestion result is missing {required_airport}")

    return {
        "capability": "lax_sna_congestion_comparison",
        "period": {
            "start": data["period_start"],
            "end": data["period_end"],
        },
        "airports": {code: airports[code] for code in ("LAX", "SNA")},
        "comparison_notes": [
            "Rates and averages should be compared separately; no universal winner is assumed.",
            "Absolute flight volume matters in addition to rates.",
            data["scope_note"],
        ],
        "methodology": data["methodology"],
        "source": data["source"],
    }


def rank_new_england_airports(
    limit: int = 3,
    processed_dir: Path | None = None,
) -> dict[str, Any]:
    """Return the top New England terminal-expansion screening candidates."""
    if not 1 <= limit <= 8:
        raise ValueError("limit must be between 1 and 8")

    data = load_processed_json("new_england_ranking.json", processed_dir)
    require_fields(
        data,
        (
            "current_period_start",
            "current_period_end",
            "comparison_period_start",
            "comparison_period_end",
            "ranking",
            "methodology",
            "scope",
            "source",
            "assumptions",
        ),
        "New England ranking data",
    )

    ranking = data["ranking"]
    if not isinstance(ranking, list) or len(ranking) < limit:
        raise ValueError("New England ranking does not contain enough airports")

    return {
        "capability": "new_england_terminal_expansion_screening",
        "period": {
            "current_start": data["current_period_start"],
            "current_end": data["current_period_end"],
            "comparison_start": data["comparison_period_start"],
            "comparison_end": data["comparison_period_end"],
        },
        "requested_limit": limit,
        "candidates": ranking[:limit],
        "methodology": data["methodology"],
        "scope": data["scope"],
        "source": data["source"],
        "assumptions": data["assumptions"],
    }


def analyze_sfo_demand_pressure(
    processed_dir: Path | None = None,
) -> dict[str, Any]:
    """Return SFO demand pressure without claiming direct unmet-passenger data."""
    data = load_processed_json("sfo_demand_pressure.json", processed_dir)
    require_fields(
        data,
        (
            "airport_code",
            "comparison_period",
            "current_period",
            "traffic",
            "scheduled_supply",
            "assessment",
            "source",
            "assumptions",
        ),
        "SFO demand-pressure data",
    )

    assessment = data["assessment"]
    if assessment.get("direct_unmet_passenger_demand_measured") is not False:
        raise ValueError(
            "SFO data contract must explicitly state that direct unmet "
            "passenger demand is not measured"
        )

    return {
        "capability": "sfo_demand_pressure",
        "airport_code": data["airport_code"],
        "period": {
            "comparison": data["comparison_period"],
            "current": data["current_period"],
        },
        "traffic": data["traffic"],
        "scheduled_supply": data["scheduled_supply"],
        "assessment": assessment,
        "source": data["source"],
        "assumptions": data["assumptions"],
    }


def list_capabilities() -> list[dict[str, str]]:
    """Describe the supported analytical scope for the conversational agent."""
    return [
        {
            "name": "get_anc_long_haul",
            "description": "Long-haul departure percentage from ANC.",
        },
        {
            "name": "compare_lax_sna_congestion",
            "description": "Operational congestion comparison for LAX and SNA.",
        },
        {
            "name": "rank_new_england_airports",
            "description": "New England terminal-expansion screening ranking.",
        },
        {
            "name": "analyze_sfo_demand_pressure",
            "description": "SFO demand-pressure and scheduled-supply-gap evidence.",
        },
    ]

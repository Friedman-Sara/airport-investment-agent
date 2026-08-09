"""LangChain wrappers around the deterministic airport business tools."""

from typing import Any

from langchain.tools import tool

from app import airport_tools as deterministic_tools


@tool("get_anc_long_haul")
def get_anc_long_haul_tool() -> dict[str, Any]:
    """Get the percentage of performed scheduled passenger departures from
    Anchorage (ANC) that are long-haul, including period, definition,
    numerator, denominator, source, and assumptions.
    """
    return deterministic_tools.get_anc_long_haul()


@tool("compare_lax_sna_congestion")
def compare_lax_sna_congestion_tool() -> dict[str, Any]:
    """Compare operational congestion at Los Angeles International (LAX) and
    John Wayne/Santa Ana (SNA), including delay, taxi-out, cancellation,
    diversion, cause mix, flight volume, period, methodology, and source.
    """
    return deterministic_tools.compare_lax_sna_congestion()


@tool("rank_new_england_airports")
def rank_new_england_airports_tool(limit: int = 3) -> dict[str, Any]:
    """Rank the top New England airport candidates for terminal-expansion
    screening using the deterministic opportunity score. Limit must be from 1
    through 8. The result does not prove profitability or terminal crowding.
    """
    return deterministic_tools.rank_new_england_airports(limit=limit)


@tool("analyze_sfo_demand_pressure")
def analyze_sfo_demand_pressure_tool() -> dict[str, Any]:
    """Analyze demand pressure and scheduled-supply delivery at San Francisco
    International (SFO). This does not directly measure passengers who wanted
    to fly but could not.
    """
    return deterministic_tools.analyze_sfo_demand_pressure()


@tool("list_supported_capabilities")
def list_supported_capabilities_tool() -> list[dict[str, str]]:
    """List the airport questions supported by the current evidence and tools.
    Use this when a request appears outside the supported MVP scope.
    """
    return deterministic_tools.list_capabilities()


AGENT_TOOLS = [
    get_anc_long_haul_tool,
    compare_lax_sna_congestion_tool,
    rank_new_england_airports_tool,
    analyze_sfo_demand_pressure_tool,
    list_supported_capabilities_tool,
]

# Airport Investment Intelligence Agent

An AI-assisted decision-support prototype for screening U.S. airport modernization opportunities. The system combines official public aviation data, deterministic Python analytics, and a conversational Google Gemini agent.

This project is built for **analyst screening**. It does **not** calculate project profitability, IRR, construction cost, or investment returns.

## Supported capabilities

- Rank a documented New England airport cohort for terminal-expansion review
- Compare operational congestion indicators for LAX and SNA
- Calculate the percentage of long-haul departures from ANC
- Assess demand pressure and scheduled-supply delivery at SFO
- Answer contextual follow-up questions within the supported evidence scope
- Ask for human clarification when a request is materially ambiguous

## Architecture

- **Python** for ingestion, validation, deterministic metrics, and agent tools
- **LangChain + Google Gemini** for intent interpretation, tool selection, and explanation
- **Processed JSON** artifacts for reproducible demo evidence
- **FastAPI + HTML/CSS/JS** chat interface

All quantitative results are calculated by tested Python functions, not by the LLM.

## Data sources

- BTS T-100 Segment Summary (public API)
- BTS T-100 Segment, All Carriers (official bulk download)
- BTS Reporting Carrier On-Time Performance (official monthly ZIP download)

`data/processed/` contains the deterministic evidence used by the chat demo.  
Large raw CSV files under `data/raw/` are gitignored; regenerate them with the scripts in `scripts/` if needed.

## Prerequisites

- Python 3.11+ recommended
- A Google Gemini API key

## Installation

From the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

On macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Environment configuration

1. Copy the example file:

```powershell
copy .env.example .env
```

2. Edit `.env` and set your key:

```env
GOOGLE_API_KEY=your_key_here
LLM_MODEL=google_genai:gemini-3.1-flash-lite
```

Optional:

```env
GOOGLE_FALLBACK_API_KEY=your_fallback_key_here
LLM_FALLBACK_MODEL=google_genai:gemini-3.1-flash-lite
```

Do not commit `.env`. Real API keys must never be stored in source files.

## Running the application

### Web chat UI

```powershell
uvicorn app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

### Terminal chat

```powershell
python .\scripts\chat_cli.py
```

## Running the tests

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

## Example questions

```text
Which airports in New England are strong candidates for terminal expansion?
```

```text
Compare LAX and SNA airport congestion levels.
```

```text
What percentage of flights out of Anchorage are long-haul?
```

```text
What is the unmet flight demand at SFO and why?
```

```text
Why might Anchorage’s long-haul share matter for modernization even if its load factor is lower than LAX and SFO?
```

## Project layout

```text
app/                 Agent, tools, and FastAPI entrypoint
frontend/            Chat UI (HTML, CSS, JS)
scripts/             Data ingestion and processing scripts
data/processed/      Deterministic evidence used by the demo
data/raw/            Local source extracts (large CSVs gitignored)
tests/               Unit tests for metrics and agent wiring
```

## Important limitations

- The New England ranking is a relative screening score, not proof of profitability or terminal crowding.
- Operational congestion metrics do not directly measure terminal capacity.
- Public BTS data does not directly measure passengers who wanted to fly but could not obtain a seat.
- Investment decisions require additional financial, engineering, regulatory, and project-specific due diligence.

## Documentation

- [Design and architecture](DESIGN.md) — scoring methodology, tradeoffs, and where AI is used

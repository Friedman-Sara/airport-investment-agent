"""Single conversational agent for airport investment intelligence."""

import os
import re
from dataclasses import dataclass, field
from typing import Any


DEFAULT_MODEL = "google_genai:gemini-3.1-flash-lite"

SYSTEM_PROMPT = """You are the Airport Investment Intelligence Agent, a
decision-support assistant for airport modernization analysts.

Rules you must follow:
1. Use an available analytical tool for every quantitative airport claim. Do
   not calculate, estimate, or invent airport values yourself.
2. Treat tool outputs as the source of truth. Preserve their period,
   definitions, numerator/denominator, assumptions, source, and limitations.
3. Explain the evidence and tradeoffs clearly. Separate measured facts from
   interpretation.
4. Never claim that a screening score proves profitability, that operational
   congestion proves terminal crowding, or that a supply gap directly measures
   passengers with unmet demand.
5. Do not declare one airport "more congested overall" unless a deterministic
   composite congestion score is provided by a tool. Compare each KPI
   separately. Higher absolute flight or delay volume indicates a larger scale
   of operational impact, not necessarily a higher congestion rate.
6. The supported MVP scope is: ANC long-haul share, LAX/SNA operational
   congestion, New England screening ranking, and SFO demand pressure. For an
   unsupported airport, period, metric, construction cost, IRR, or profit
   request, state the limitation and say what additional data would be needed.
7. Ask a clarifying question when a request is materially ambiguous. For
   example, "LA airport" could mean LAX or another Los Angeles-area airport.
8. Use conversation context for follow-up questions, but call the relevant
   tool again when factual evidence is needed.
9. Answer in the language used by the user. Be concise but include the key
   reasoning, assumptions, and uncertainty.
10. You provide analyst support only. A human must approve investment
   shortlists and any change to scoring assumptions.
"""


class AgentConfigurationError(RuntimeError):
    """Raised when the conversational agent cannot be configured."""


@dataclass
class AgentRuntime:
    """Hold the agent graph and non-durable pending HITL clarifications."""

    graph: Any
    pending_requests: dict[str, str] = field(default_factory=dict)

    def invoke(self, payload: dict[str, Any], config: dict[str, Any]):
        return self.graph.invoke(payload, config=config)


def _google_api_keys() -> tuple[str | None, str | None]:
    primary = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    fallback = os.getenv("GOOGLE_FALLBACK_API_KEY")

    # Repeating the same credential does not provide failover.
    if fallback == primary:
        fallback = None

    return primary, fallback


def _gemini_model_id(model_name: str) -> str:
    """Convert LangChain's provider:model notation to a Gemini model ID."""
    prefix = "google_genai:"
    return model_name[len(prefix) :] if model_name.startswith(prefix) else model_name


def _required_clarification(question: str) -> str | None:
    """Deterministically pause materially ambiguous Los Angeles requests."""
    normalized = re.sub(r"\s+", " ", question.strip().lower())
    has_specific_code = any(code in normalized for code in ("lax", "bur", "lgb"))
    ambiguous_la = (
        re.search(r"\bla airport\b", normalized) is not None
        or re.search(r"\blos angeles airport\b", normalized) is not None
    )

    if ambiguous_la and not has_specific_code:
        if re.search(r"[\u0590-\u05FF]", question):
            return (
                "לאיזה שדה תעופה באזור לוס אנג׳לס התכוונת — "
                "LAX,‏ BUR,‏ LGB או שדה אחר? יכולת ההשוואה הנוכחית "
                "תומכת ב־LAX מול SNA."
            )
        return (
            "Which Los Angeles-area airport do you mean—LAX, BUR, LGB, "
            "or another airport? The current comparison capability supports "
            "LAX versus SNA."
        )

    return None


def build_agent(
    model_name: str | None = None,
    *,
    load_env_file: bool = True,
):
    """Build one LangChain agent with thread-scoped in-memory conversation."""
    if load_env_file:
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ModuleNotFoundError:
            # Keep module import and configuration tests usable before optional
            # agent dependencies are installed. The actionable error below
            # tells the user what to install or configure.
            pass

    primary_key, fallback_key = _google_api_keys()
    if not primary_key:
        raise AgentConfigurationError(
            "Missing Gemini API key. Set GOOGLE_API_KEY or GEMINI_API_KEY "
            "in the local .env file."
        )

    try:
        from langchain.agents import create_agent
        from langchain.agents.middleware import ModelFallbackMiddleware
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langgraph.checkpoint.memory import InMemorySaver

        from app.agent_tools import AGENT_TOOLS
    except ModuleNotFoundError as error:
        raise AgentConfigurationError(
            "Agent dependencies are missing. Run: "
            "python -m pip install -r requirements.txt"
        ) from error

    configured_model = model_name or os.getenv("LLM_MODEL", DEFAULT_MODEL)
    primary_model = ChatGoogleGenerativeAI(
        model=_gemini_model_id(configured_model),
        api_key=primary_key,
        timeout=60,
        max_retries=2,
    )

    middleware = []
    if fallback_key:
        fallback_model_name = os.getenv("LLM_FALLBACK_MODEL", configured_model)
        fallback_model = ChatGoogleGenerativeAI(
            model=_gemini_model_id(fallback_model_name),
            api_key=fallback_key,
            timeout=60,
            max_retries=2,
        )
        middleware.append(ModelFallbackMiddleware(fallback_model))

    graph = create_agent(
        model=primary_model,
        tools=AGENT_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        checkpointer=InMemorySaver(),
        middleware=middleware,
    )
    return AgentRuntime(graph=graph)


def extract_answer(result: dict[str, Any]) -> str:
    """Extract text from the final agent message across common content forms."""
    messages = result.get("messages", [])
    if not messages:
        raise ValueError("Agent returned no messages")

    content = messages[-1].content
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text_parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                text_parts.append(block["text"])
        if text_parts:
            return "\n".join(text_parts)

    return str(content)


def ask_agent(agent: Any, question: str, thread_id: str) -> str:
    """Ask a question while preserving follow-up context for one thread."""
    if not question.strip():
        raise ValueError("question must not be empty")
    if not thread_id.strip():
        raise ValueError("thread_id must not be empty")

    clarification = _required_clarification(question)
    if clarification:
        if isinstance(agent, AgentRuntime):
            agent.pending_requests[thread_id] = question
        return clarification

    if isinstance(agent, AgentRuntime) and thread_id in agent.pending_requests:
        original_request = agent.pending_requests.pop(thread_id)
        question = (
            "Original request that required human clarification:\n"
            f"{original_request}\n\n"
            "Human clarification:\n"
            f"{question}"
        )

    result = agent.invoke(
        {"messages": [{"role": "user", "content": question}]},
        config={"configurable": {"thread_id": thread_id}},
    )
    return extract_answer(result)

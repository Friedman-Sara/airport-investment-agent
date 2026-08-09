import os
import unittest
from unittest.mock import patch

from app.agent import (
    AgentConfigurationError,
    AgentRuntime,
    DEFAULT_MODEL,
    SYSTEM_PROMPT,
    _gemini_model_id,
    _google_api_keys,
    ask_agent,
    build_agent,
    extract_answer,
)


class Message:
    def __init__(self, content):
        self.content = content


class FakeAgent:
    def __init__(self):
        self.received = None

    def invoke(self, payload, config):
        self.received = (payload, config)
        return {"messages": [Message("deterministic answer")]}


class FakeGraph(FakeAgent):
    pass


class AgentTests(unittest.TestCase):
    def test_default_model_is_google_gemini(self):
        self.assertEqual(DEFAULT_MODEL, "google_genai:gemini-3.1-flash-lite")

    def test_model_provider_prefix_is_removed_for_google_client(self):
        self.assertEqual(
            _gemini_model_id("google_genai:gemini-3.1-flash-lite"),
            "gemini-3.1-flash-lite",
        )

    def test_primary_and_distinct_fallback_keys_are_loaded(self):
        with patch.dict(
            os.environ,
            {
                "GOOGLE_API_KEY": "primary-test-key",
                "GOOGLE_FALLBACK_API_KEY": "fallback-test-key",
            },
            clear=True,
        ):
            self.assertEqual(
                _google_api_keys(),
                ("primary-test-key", "fallback-test-key"),
            )

    def test_missing_key_has_actionable_error_before_importing_langchain(self):
        # Disable .env loading so the test truly represents a machine with no
        # configured key and remains independent of the developer's real file.
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(AgentConfigurationError, "API key"):
                build_agent(load_env_file=False)

    def test_prompt_contains_business_guardrails(self):
        self.assertIn("quantitative airport claim", SYSTEM_PROMPT)
        self.assertIn("Never claim", SYSTEM_PROMPT)
        self.assertIn("more congested overall", SYSTEM_PROMPT)
        self.assertIn("not necessarily a higher congestion rate", SYSTEM_PROMPT)
        self.assertIn("Ask a clarifying question", SYSTEM_PROMPT)
        self.assertIn("LA airport", SYSTEM_PROMPT)
        self.assertIn("human must approve", SYSTEM_PROMPT)

    def test_extract_answer_supports_text_blocks(self):
        result = {
            "messages": [
                Message(
                    [
                        {"type": "text", "text": "first"},
                        {"type": "text", "text": "second"},
                    ]
                )
            ]
        }
        self.assertEqual(extract_answer(result), "first\nsecond")

    def test_ask_agent_passes_thread_id_for_follow_up_memory(self):
        agent = FakeAgent()
        answer = ask_agent(agent, "Compare the airports", "demo-thread")
        self.assertEqual(answer, "deterministic answer")
        self.assertEqual(
            agent.received[1],
            {"configurable": {"thread_id": "demo-thread"}},
        )

    def test_ask_agent_rejects_empty_input(self):
        with self.assertRaisesRegex(ValueError, "question"):
            ask_agent(FakeAgent(), "   ", "demo-thread")

    def test_ambiguous_la_request_pauses_before_model_call(self):
        graph = FakeGraph()
        runtime = AgentRuntime(graph=graph)

        answer = ask_agent(
            runtime,
            "Compare LA airport with Santa Ana.",
            "hitl-thread",
        )

        self.assertIn("Which Los Angeles-area airport", answer)
        self.assertIsNone(graph.received)
        self.assertIn("hitl-thread", runtime.pending_requests)

    def test_human_clarification_resumes_the_pending_request(self):
        graph = FakeGraph()
        runtime = AgentRuntime(graph=graph)

        ask_agent(
            runtime,
            "Compare LA airport with Santa Ana.",
            "hitl-thread",
        )
        answer = ask_agent(runtime, "I mean LAX.", "hitl-thread")

        self.assertEqual(answer, "deterministic answer")
        sent_question = graph.received[0]["messages"][0]["content"]
        self.assertIn("Compare LA airport with Santa Ana", sent_question)
        self.assertIn("I mean LAX", sent_question)
        self.assertNotIn("hitl-thread", runtime.pending_requests)


if __name__ == "__main__":
    unittest.main()

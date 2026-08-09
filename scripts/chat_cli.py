"""Run the airport agent as a simple terminal chat."""

import sys
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agent import AgentConfigurationError, ask_agent, build_agent


def main() -> None:
    try:
        agent = build_agent()
    except AgentConfigurationError as error:
        raise SystemExit(f"Configuration error: {error}") from error

    thread_id = str(uuid4())
    print("Airport Investment Intelligence Agent")
    print("Type 'exit' to finish. Follow-up questions keep the same context.\n")

    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            return

        if question.lower() in {"exit", "quit"}:
            print("Goodbye.")
            return
        if not question:
            continue

        try:
            answer = ask_agent(agent, question, thread_id)
        except Exception as error:
            print(f"Agent error: {error}\n")
            continue

        print(f"\nAgent: {answer}\n")


if __name__ == "__main__":
    main()

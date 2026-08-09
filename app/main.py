"""FastAPI chat UI for the Airport Investment Intelligence Agent."""

from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agent import AgentConfigurationError, ask_agent, build_agent


FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"

app = FastAPI(
    title="Airport Investment Intelligence Agent",
    version="0.1.0",
)

app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend")

_agent = None


def get_agent():
    """Build the agent once per process."""
    global _agent
    if _agent is None:
        try:
            _agent = build_agent()
        except AgentConfigurationError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
    return _agent


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)
    thread_id: str | None = None


class ChatResponse(BaseModel):
    answer: str
    thread_id: str


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question must not be empty")

    thread_id = (request.thread_id or "").strip() or str(uuid4())

    try:
        answer = ask_agent(get_agent(), question, thread_id)
    except AgentConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Agent error: {error}",
        ) from error

    return ChatResponse(answer=answer, thread_id=thread_id)

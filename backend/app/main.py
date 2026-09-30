import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.agent import run_agent
from app.config import settings
from app.db import SessionLocal, get_db, utcnow
from app.llm import LLMError
from app.models import Conversation
from app.seed import initialize

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize()
    with SessionLocal() as db:
        db.execute(
            delete(Conversation).where(
                Conversation.updated_at < utcnow() - timedelta(days=30)
            )
        )
        db.commit()
    yield


app = FastAPI(
    title="SmartOps Agent",
    description="支持 Function Calling、多步工具执行和对话记忆的智能运营助手。",
    version="1.0.0",
    lifespan=lifespan,
)
frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("消息不能为空。")
        return value.strip()

    @field_validator("session_id")
    @classmethod
    def session_id_must_be_uuid(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                UUID(value)
            except ValueError as exc:
                raise ValueError("session_id 必须是有效的 UUID。") from exc
        return value


def _chart_from_calls(tool_calls: list[dict]) -> dict | None:
    for call in reversed(tool_calls):
        result = call.get("result")
        if call.get("name") == "generate_chart" and isinstance(result, dict):
            return result
    return None


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(frontend_dir / "index.html")


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "llm_configured": bool(settings.llm_api_key),
        "mode": "live" if settings.llm_api_key else "demo",
    }


@app.post("/api/chat")
async def chat(payload: ChatRequest, db: Session = Depends(get_db)) -> dict:
    session_id = payload.session_id or str(uuid4())
    conversation = db.get(Conversation, session_id)
    if conversation is None:
        conversation = Conversation(id=session_id, messages_json="[]")
        db.add(conversation)
        history: list[dict[str, str]] = []
    else:
        history = json.loads(conversation.messages_json)

    try:
        result = await run_agent(db, payload.message, history)
    except LLMError as exc:
        db.rollback()
        logger.warning("Chat request failed because LLM service returned an error")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    history.extend(
        [
            {"role": "user", "content": payload.message},
            {"role": "assistant", "content": result["answer"]},
        ]
    )
    conversation.messages_json = json.dumps(history[-10:], ensure_ascii=False)
    conversation.updated_at = utcnow()
    db.commit()
    return {
        "session_id": session_id,
        "answer": result["answer"],
        "tool_calls": result["tool_calls"],
        "chart": _chart_from_calls(result["tool_calls"]),
        "mode": result["mode"],
    }

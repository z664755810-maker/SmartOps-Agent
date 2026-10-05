import json
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.agent import run_agent
from app.config import settings
from app.db import SessionLocal, get_db, utcnow
from app.llm import LLMError
from app.models import Conversation, NotificationLog, Order, Product, Stock
from app.seed import initialize
from app.tools import list_products, query_sales, query_sales_trend, query_top_products

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


def _dashboard_data(db: Session, days: int) -> dict:
    today = date.today()
    start = today - timedelta(days=days - 1)
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=days - 1)
    current = query_sales(
        db, {"start_date": start.isoformat(), "end_date": today.isoformat()}
    )
    previous = query_sales(
        db,
        {
            "start_date": previous_start.isoformat(),
            "end_date": previous_end.isoformat(),
        },
    )
    trend = query_sales_trend(
        db, {"start_date": start.isoformat(), "end_date": today.isoformat()}
    )
    top_products = query_top_products(
        db,
        {
            "start_date": start.isoformat(),
            "end_date": today.isoformat(),
            "limit": 5,
        },
    )
    inventory = list_products(db, {"low_stock_below": 20, "limit": 100})
    total_products = db.scalar(select(func.count()).select_from(Product)) or 0
    low_stock_count = db.scalar(
        select(func.count())
        .select_from(Stock)
        .where(Stock.quantity < 20)
    ) or 0
    recent_notifications = db.execute(
        select(NotificationLog)
        .order_by(NotificationLog.created_at.desc())
        .limit(5)
    ).scalars().all()
    change_percent = None
    if previous["sales_amount"] > 0:
        change_percent = round(
            (current["sales_amount"] - previous["sales_amount"])
            / previous["sales_amount"]
            * 100,
            1,
        )

    return {
        "period": {
            "start_date": start.isoformat(),
            "end_date": today.isoformat(),
            "days": days,
        },
        "kpis": {
            "sales_amount": current["sales_amount"],
            "order_count": current["order_count"],
            "units_sold": current["units_sold"],
            "average_order_value": round(
                current["sales_amount"] / current["order_count"], 2
            )
            if current["order_count"]
            else 0,
            "sales_change_percent": change_percent,
            "previous_sales_amount": previous["sales_amount"],
            "product_count": total_products,
            "low_stock_count": low_stock_count,
            "notification_count": db.scalar(
                select(func.count()).select_from(NotificationLog)
            )
            or 0,
        },
        "trend": trend["trend"],
        "top_products": top_products["products"],
        "low_stock_products": inventory["products"],
        "recent_notifications": [
            {
                "id": notification.id,
                "channel": notification.channel,
                "message": notification.message,
                "created_at": notification.created_at.isoformat(),
            }
            for notification in recent_notifications
        ],
    }


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


@app.get("/api/dashboard")
def dashboard(
    days: int = Query(default=7, ge=7, le=90),
    db: Session = Depends(get_db),
) -> dict:
    return _dashboard_data(db, days)


@app.get("/api/products")
def products(
    search: str = Query(default="", max_length=100),
    category: str = Query(default="", max_length=50),
    low_stock_below: int | None = Query(default=None, ge=0, le=100000),
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    result = list_products(
        db,
        {
            "search": search,
            "category": category,
            "low_stock_below": low_stock_below,
            "limit": limit,
        },
    )
    result["categories"] = db.scalars(
        select(Product.category).distinct().order_by(Product.category)
    ).all()
    return result


@app.get("/api/sessions")
def list_sessions(db: Session = Depends(get_db)) -> dict:
    conversations = db.scalars(
        select(Conversation).order_by(Conversation.updated_at.desc()).limit(50)
    ).all()
    items = []
    for conversation in conversations:
        messages = json.loads(conversation.messages_json)
        first_user = next(
            (
                message.get("content", "")
                for message in messages
                if message.get("role") == "user"
            ),
            "",
        )
        last_message = messages[-1].get("content", "") if messages else ""
        items.append(
            {
                "session_id": conversation.id,
                "title": first_user[:36] or "新对话",
                "preview": last_message[:70],
                "updated_at": conversation.updated_at.isoformat(),
            }
        )
    return {"sessions": items}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: UUID, db: Session = Depends(get_db)) -> dict:
    conversation = db.get(Conversation, str(session_id))
    if conversation is None:
        raise HTTPException(status_code=404, detail="找不到该会话。")
    return {
        "session_id": conversation.id,
        "messages": json.loads(conversation.messages_json),
        "updated_at": conversation.updated_at.isoformat(),
    }


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: UUID, db: Session = Depends(get_db)) -> dict:
    conversation = db.get(Conversation, str(session_id))
    if conversation is None:
        raise HTTPException(status_code=404, detail="找不到该会话。")
    db.delete(conversation)
    db.commit()
    return {"deleted": True, "session_id": str(session_id)}


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
            {
                "role": "assistant",
                "content": result["answer"],
                "tool_calls": result["tool_calls"],
                "chart": _chart_from_calls(result["tool_calls"]),
                "mode": result["mode"],
            },
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

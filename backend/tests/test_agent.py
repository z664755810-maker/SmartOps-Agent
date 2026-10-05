from collections.abc import Generator
import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app import agent
from app.main import app
from app.seed import initialize_database
from app.models import NotificationLog, Order, Product, Stock
from app.tools import TOOL_DEFINITIONS, execute_tool


@pytest.fixture()
def db() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    test_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with test_session() as session:
        initialize_database(session)
        yield session
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def client(db: Session) -> Generator[TestClient, None, None]:
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_sales_query_includes_both_requested_dates(db: Session) -> None:
    result = execute_tool(
        db,
        "query_sales",
        {"start_date": "2020-01-01", "end_date": "2020-01-02"},
    )
    assert result == {
        "start_date": "2020-01-01",
        "end_date": "2020-01-02",
        "sales_amount": 0.0,
        "order_count": 0,
        "units_sold": 0,
    }


def test_seed_data_has_expected_product_order_and_stock_counts(db: Session) -> None:
    assert db.scalar(select(func.count()).select_from(Product)) == 20
    assert db.scalar(select(func.count()).select_from(Order)) == 200
    assert db.scalar(select(func.count()).select_from(Stock)) == 20


def test_model_tool_definitions_are_complete_and_unique() -> None:
    names = [definition["function"]["name"] for definition in TOOL_DEFINITIONS]
    assert len(names) == len(set(names))
    assert {
        "query_sales",
        "query_top_products",
        "query_sales_trend",
        "query_stock",
        "list_products",
        "generate_chart",
        "send_notification",
    } <= set(names)


def test_stock_query_returns_inventory(db: Session) -> None:
    result = execute_tool(db, "query_stock", {"product_name": "无线鼠标"})
    assert result["product_name"] == "无线鼠标"
    assert result["stock_quantity"] > 0


def test_product_list_filters_search_category_and_low_stock(db: Session) -> None:
    result = execute_tool(
        db,
        "list_products",
        {"search": "耳机", "category": "数码配件", "low_stock_below": 1000},
    )
    assert result["count"] == 2
    assert all(item["low_stock"] for item in result["products"])


def test_tool_rejects_invalid_date_range(db: Session) -> None:
    with pytest.raises(ValueError, match="开始日期不能晚于结束日期"):
        execute_tool(
            db,
            "query_sales",
            {"start_date": "2026-09-30", "end_date": "2026-09-01"},
        )


def test_stock_query_reports_ambiguous_name(db: Session) -> None:
    with pytest.raises(ValueError, match="商品名称不唯一"):
        execute_tool(db, "query_stock", {"product_name": "耳机"})


def test_chart_rejects_mismatched_or_non_finite_values() -> None:
    with pytest.raises(ValueError, match="一一对应"):
        execute_tool(
            None,  # type: ignore[arg-type]
            "generate_chart",
            {"title": "销量", "labels": ["鼠标"], "values": [], "chart_type": "bar"},
        )
    with pytest.raises(ValueError, match="有限的非负数字"):
        execute_tool(
            None,  # type: ignore[arg-type]
            "generate_chart",
            {
                "title": "销量",
                "labels": ["鼠标"],
                "values": [float("nan")],
                "chart_type": "bar",
            },
        )


def test_multi_tool_demo_workflow_returns_chart_and_simulated_notice(
    client: TestClient, db: Session
) -> None:
    response = client.post(
        "/api/chat",
        json={"message": "把上周销量最高的 3 个商品画成柱状图并发群"},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["mode"] == "demo"
    assert [call["name"] for call in result["tool_calls"]] == [
        "query_top_products",
        "generate_chart",
        "send_notification",
    ]
    assert result["tool_calls"][0]["arguments"]["limit"] == 3
    assert result["chart"]["chart_type"] == "bar"
    assert "不会实际发送" in result["answer"]
    assert db.scalar(select(func.count()).select_from(NotificationLog)) == 1
    dashboard = client.get("/api/dashboard").json()
    assert dashboard["kpis"]["notification_count"] == 1
    assert dashboard["recent_notifications"][0]["channel"] == "wechat"
    assert "销量排行" in dashboard["recent_notifications"][0]["message"]


def test_follow_up_uses_conversation_to_calculate_sales_change(
    client: TestClient,
) -> None:
    first = client.post("/api/chat", json={"message": "查上周销售额"})
    session_id = first.json()["session_id"]
    second = client.post(
        "/api/chat", json={"message": "那环比呢", "session_id": session_id}
    )
    assert second.status_code == 200
    assert "环比" in second.json()["answer"]
    assert len(second.json()["tool_calls"]) == 2


def test_dashboard_exposes_kpis_trend_top_products_and_inventory(
    client: TestClient,
) -> None:
    response = client.get("/api/dashboard?days=30")
    assert response.status_code == 200
    result = response.json()
    assert result["period"]["days"] == 30
    assert result["kpis"]["product_count"] == 20
    assert len(result["trend"]) == 30
    assert len(result["top_products"]) <= 5
    assert all("date" in item and "sales_amount" in item for item in result["trend"])
    assert "low_stock_count" in result["kpis"]


def test_products_api_supports_search_categories_and_low_stock(
    client: TestClient,
) -> None:
    response = client.get("/api/products?search=耳机&low_stock_below=1000")
    assert response.status_code == 200
    result = response.json()
    assert result["count"] == 2
    assert len(result["categories"]) >= 1
    assert all(item["low_stock"] for item in result["products"])


def test_conversation_history_restores_tool_trace_and_can_be_deleted(
    client: TestClient,
) -> None:
    first = client.post(
        "/api/chat",
        json={"message": "生成近 30 天销售趋势图"},
    )
    assert first.status_code == 200
    session_id = first.json()["session_id"]
    history = client.get(f"/api/sessions/{session_id}")
    assert history.status_code == 200
    messages = history.json()["messages"]
    assistant_message = messages[-1]
    assert assistant_message["role"] == "assistant"
    assert assistant_message["chart"]["title"] == "每周销售额趋势"
    assert [call["name"] for call in assistant_message["tool_calls"]] == [
        "query_sales_trend",
        "generate_chart",
    ]
    session_list = client.get("/api/sessions").json()["sessions"]
    assert session_list[0]["session_id"] == session_id
    assert client.delete(f"/api/sessions/{session_id}").json()["deleted"] is True
    assert client.get(f"/api/sessions/{session_id}").status_code == 404


def test_low_stock_follow_up_sends_simulated_notification(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/chat",
        json={"message": "列出库存少于 40 件的商品并发群"},
    )
    assert response.status_code == 200
    names = [call["name"] for call in response.json()["tool_calls"]]
    assert names == ["list_products", "send_notification"]
    assert "不会实际发送" in response.json()["answer"]


def test_stock_lookup_can_be_followed_by_notification_summary(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/chat",
        json={"message": "先查无线鼠标库存，再总结成一条企业微信通知"},
    )
    assert response.status_code == 200
    result = response.json()
    assert [call["name"] for call in result["tool_calls"]] == [
        "query_stock",
        "send_notification",
    ]
    assert "无线鼠标" in result["answer"]
    assert "演示日志" in result["answer"]


def test_unknown_or_blank_input_is_rejected(client: TestClient) -> None:
    assert client.post("/api/chat", json={"message": "   "}).status_code == 422
    assert (
        client.post(
            "/api/chat",
            json={"message": "查库存", "session_id": "not-a-uuid"},
        ).status_code
        == 422
    )


def test_live_agent_returns_tool_errors_to_model(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent.settings, "llm_api_key", "test-key")
    responses = iter(
        [
            {
                "tool_calls": [
                    {
                        "id": "call-1",
                        "function": {
                            "name": "query_stock",
                            "arguments": json.dumps({"product_name": "不存在的商品"}),
                        },
                    }
                ]
            },
            {"content": "没有找到匹配的商品。"},
        ]
    )
    observed_messages: list[dict] = []

    async def fake_completion(messages: list[dict]) -> dict:
        observed_messages.extend(messages)
        return next(responses)

    monkeypatch.setattr(agent, "chat_completion", fake_completion)
    result = asyncio.run(agent.run_agent(db, "查库存", []))
    assert result["mode"] == "live"
    assert result["answer"] == "没有找到匹配的商品。"
    assert "error" in result["tool_calls"][0]
    tool_message = next(message for message in observed_messages if message["role"] == "tool")
    assert "没有找到" in tool_message["content"]


def test_live_agent_stops_at_configured_step_limit(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(agent.settings, "max_agent_steps", 2)
    calls = 0

    async def endless_tool_call(_: list[dict]) -> dict:
        nonlocal calls
        calls += 1
        return {
            "tool_calls": [
                {
                    "id": f"call-{calls}",
                    "function": {
                        "name": "query_sales",
                        "arguments": json.dumps(
                            {"start_date": "2026-09-01", "end_date": "2026-09-02"}
                        ),
                    },
                }
            ]
        }

    monkeypatch.setattr(agent, "chat_completion", endless_tool_call)
    result = asyncio.run(agent.run_agent(db, "查销售额", []))
    assert calls == 2
    assert len(result["tool_calls"]) == 1
    assert "达到上限" in result["answer"]

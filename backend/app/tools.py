import math
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import NotificationLog, Order, Product, Stock

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "query_sales",
            "description": "查询指定日期范围内的销售额、订单数和商品件数。结束日期包含在内。",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "开始日期，YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "结束日期，YYYY-MM-DD"},
                },
                "required": ["start_date", "end_date"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_top_products",
            "description": "查询指定日期范围内销量最高的商品，按销量降序返回商品数量和销售额。",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "开始日期，YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "结束日期，YYYY-MM-DD"},
                    "limit": {"type": "integer", "description": "返回条数，1 到 20"},
                },
                "required": ["start_date", "end_date"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_sales_trend",
            "description": "查询指定日期范围内逐日销售额和订单数，可用于发现日趋势。最多查询 90 天。",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "开始日期，YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "结束日期，YYYY-MM-DD"},
                },
                "required": ["start_date", "end_date"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_stock",
            "description": "按商品名称查询当前库存；名称不唯一或不存在时会返回可处理的错误。",
            "parameters": {
                "type": "object",
                "properties": {"product_name": {"type": "string"}},
                "required": ["product_name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_products",
            "description": "列出商品和库存，可按商品名称或分类筛选，并设置低库存阈值。",
            "parameters": {
                "type": "object",
                "properties": {
                    "search": {"type": "string"},
                    "category": {"type": "string"},
                    "low_stock_below": {"type": "integer"},
                    "limit": {"type": "integer"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_chart",
            "description": "将已经查询到的标签和数值组织成柱状图或饼图数据，供前端展示。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "labels": {"type": "array", "items": {"type": "string"}},
                    "values": {"type": "array", "items": {"type": "number"}},
                    "chart_type": {"type": "string", "enum": ["bar", "pie"]},
                },
                "required": ["title", "labels", "values", "chart_type"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_notification",
            "description": "向邮件或企业微信发送业务通知；演示版仅写入本地通知日志，不会连接外部服务。",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "通知正文，最多 1000 字"},
                    "channel": {"type": "string", "enum": ["email", "wechat"]},
                },
                "required": ["message", "channel"],
                "additionalProperties": False,
            },
        },
    },
]


def _date_range(arguments: dict[str, Any]) -> tuple[datetime, datetime, date, date]:
    try:
        start = date.fromisoformat(arguments["start_date"])
        end = date.fromisoformat(arguments["end_date"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("日期格式无效，请使用 YYYY-MM-DD，且提供开始和结束日期。") from exc
    if start > end:
        raise ValueError("开始日期不能晚于结束日期。")
    if (end - start).days > 366:
        raise ValueError("单次查询日期范围不能超过 367 天。")
    return (
        datetime.combine(start, time.min),
        datetime.combine(end + timedelta(days=1), time.min),
        start,
        end,
    )


def query_sales(db: Session, arguments: dict[str, Any]) -> dict[str, Any]:
    start, end_exclusive, start_date, end_date = _date_range(arguments)
    total, orders, units = db.execute(
        select(
            func.coalesce(func.sum(Order.amount), 0),
            func.count(Order.id),
            func.coalesce(func.sum(Order.quantity), 0),
        ).where(Order.created_at >= start, Order.created_at < end_exclusive)
    ).one()
    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "sales_amount": round(float(total), 2),
        "order_count": int(orders),
        "units_sold": int(units),
    }


def query_top_products(db: Session, arguments: dict[str, Any]) -> dict[str, Any]:
    start, end_exclusive, start_date, end_date = _date_range(arguments)
    limit = arguments.get("limit", 5)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
        raise ValueError("limit 必须是 1 到 20 之间的整数。")
    rows = db.execute(
        select(
            Product.name,
            func.sum(Order.quantity).label("units_sold"),
            func.sum(Order.amount).label("sales_amount"),
        )
        .join(Order, Order.product_id == Product.id)
        .where(Order.created_at >= start, Order.created_at < end_exclusive)
        .group_by(Product.id, Product.name)
        .order_by(func.sum(Order.quantity).desc(), Product.name.asc())
        .limit(limit)
    ).all()
    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "products": [
            {
                "name": name,
                "units_sold": int(units),
                "sales_amount": round(float(amount), 2),
            }
            for name, units, amount in rows
        ],
    }


def query_sales_trend(db: Session, arguments: dict[str, Any]) -> dict[str, Any]:
    start, end_exclusive, start_date, end_date = _date_range(arguments)
    if (end_date - start_date).days > 89:
        raise ValueError("趋势图最多支持 90 天，请缩短日期范围。")
    rows = db.execute(
        select(
            func.date(Order.created_at).label("sales_date"),
            func.coalesce(func.sum(Order.amount), 0),
            func.count(Order.id),
        )
        .where(Order.created_at >= start, Order.created_at < end_exclusive)
        .group_by(func.date(Order.created_at))
        .order_by(func.date(Order.created_at))
    ).all()
    values = {
        str(day): {"sales_amount": round(float(amount), 2), "order_count": int(count)}
        for day, amount, count in rows
    }
    trend = []
    current_day = start_date
    while current_day <= end_date:
        day = current_day.isoformat()
        trend.append(
            {
                "date": day,
                "sales_amount": values.get(day, {}).get("sales_amount", 0),
                "order_count": values.get(day, {}).get("order_count", 0),
            }
        )
        current_day += timedelta(days=1)
    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "trend": trend,
    }


def query_stock(db: Session, arguments: dict[str, Any]) -> dict[str, Any]:
    name = arguments.get("product_name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("请提供要查询的商品名称。")
    escaped_name = (
        name.strip().replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    )
    matches = db.execute(
        select(Product.name, Stock.quantity)
        .join(Stock, Stock.product_id == Product.id)
        .where(Product.name.ilike(f"%{escaped_name}%", escape="\\"))
        .order_by(Product.name)
        .limit(6)
    ).all()
    if not matches:
        raise ValueError(f"没有找到名称包含“{name.strip()}”的商品。")
    if len(matches) > 1:
        names = "、".join(product_name for product_name, _ in matches[:5])
        raise ValueError(f"商品名称不唯一，请指定更完整的名称。匹配项：{names}")
    product_name, quantity = matches[0]
    return {"product_name": product_name, "stock_quantity": quantity}


def list_products(db: Session, arguments: dict[str, Any]) -> dict[str, Any]:
    search = arguments.get("search", "")
    category = arguments.get("category", "")
    limit = arguments.get("limit", 50)
    low_stock_below = arguments.get("low_stock_below")
    if not isinstance(search, str) or not isinstance(category, str):
        raise ValueError("商品名称和分类筛选必须是文本。")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit 必须是 1 到 100 之间的整数。")
    if low_stock_below is not None and (
        isinstance(low_stock_below, bool)
        or not isinstance(low_stock_below, int)
        or not 0 <= low_stock_below <= 100000
    ):
        raise ValueError("低库存阈值必须是非负整数。")

    statement = (
        select(Product.name, Product.category, Product.price, Stock.quantity)
        .join(Stock, Stock.product_id == Product.id)
        .order_by(Product.category, Product.name)
    )
    if search.strip():
        escaped_search = (
            search.strip()
            .replace("\\", "\\\\")
            .replace("%", r"\%")
            .replace("_", r"\_")
        )
        statement = statement.where(
            Product.name.ilike(f"%{escaped_search}%", escape="\\")
        )
    if category.strip():
        statement = statement.where(Product.category == category.strip())
    if low_stock_below is not None:
        statement = statement.where(Stock.quantity < low_stock_below)
    rows = db.execute(statement.limit(limit)).all()
    return {
        "products": [
            {
                "name": name,
                "category": category_name,
                "price": round(float(price), 2),
                "stock_quantity": stock,
                "low_stock": stock < low_stock_below
                if low_stock_below is not None
                else False,
            }
            for name, category_name, price, stock in rows
        ],
        "count": len(rows),
    }


def generate_chart(arguments: dict[str, Any]) -> dict[str, Any]:
    title = arguments.get("title")
    labels = arguments.get("labels")
    values = arguments.get("values")
    chart_type = arguments.get("chart_type")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("图表标题不能为空。")
    if chart_type not in {"bar", "pie"}:
        raise ValueError("图表类型必须是 bar 或 pie。")
    if not isinstance(labels, list) or not isinstance(values, list):
        raise ValueError("图表标签和数值必须是列表。")
    if not labels or len(labels) != len(values) or len(labels) > 20:
        raise ValueError("图表标签和数值须一一对应，且包含 1 到 20 项。")
    if any(not isinstance(label, str) or not label.strip() for label in labels):
        raise ValueError("图表标签必须是非空文本。")
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        for value in values
    ):
        raise ValueError("图表数值必须是有限的非负数字。")
    return {
        "title": title.strip()[:100],
        "chart_type": chart_type,
        "labels": [label[:80] for label in labels],
        "values": [float(value) for value in values],
    }


def send_notification(db: Session, arguments: dict[str, Any]) -> dict[str, Any]:
    message = arguments.get("message")
    channel = arguments.get("channel")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("通知内容不能为空。")
    if len(message) > 1000:
        raise ValueError("通知内容不能超过 1000 字。")
    if channel not in {"email", "wechat"}:
        raise ValueError("通知渠道必须是 email 或 wechat。")
    log = NotificationLog(channel=channel, message=message.strip())
    db.add(log)
    db.commit()
    return {
        "status": "simulated",
        "channel": channel,
        "message": "通知已写入演示日志；当前未连接外部邮件或企业微信服务。",
        "notification_id": log.id,
    }


def execute_tool(db: Session, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ValueError("工具参数必须是 JSON 对象。")
    if name == "query_sales":
        return query_sales(db, arguments)
    if name == "query_top_products":
        return query_top_products(db, arguments)
    if name == "query_sales_trend":
        return query_sales_trend(db, arguments)
    if name == "query_stock":
        return query_stock(db, arguments)
    if name == "list_products":
        return list_products(db, arguments)
    if name == "generate_chart":
        return generate_chart(arguments)
    if name == "send_notification":
        return send_notification(db, arguments)
    raise ValueError(f"不支持的工具：{name}")

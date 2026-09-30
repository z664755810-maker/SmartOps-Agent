import json
import logging
import re
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.llm import LLMError, chat_completion
from app.tools import execute_tool

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个面向业务人员的智能运营助手，只能基于工具查询结果回答销售、商品、库存、图表和通知相关问题。
需要真实业务数据时必须调用工具，不得猜测或编造数据。可连续调用多个工具完成任务；先查询，再用查询结果生成图表或通知。
日期按 YYYY-MM-DD 传递；用户说“上周”时使用完整的上一自然周。遇到工具错误时先解释错误，必要时调整参数重试。
通知工具当前是演示功能，只写本地日志，不会真的发送邮件或企业微信；必须向用户明确说明。
无关问题请礼貌说明你只支持销售、商品排行、库存、图表和通知。用简洁中文作答，并说明采用的日期范围。"""


def _resolve_period(text: str) -> tuple[date, date]:
    today = date.today()
    if "上周" in text:
        this_monday = today - timedelta(days=today.weekday())
        return this_monday - timedelta(days=7), this_monday - timedelta(days=1)
    if "本周" in text or "这周" in text:
        return today - timedelta(days=today.weekday()), today
    if "本月" in text or "这个月" in text:
        return today.replace(day=1), today
    match = re.search(r"(?:最近|近)\s*(\d{1,3})\s*天", text)
    if match:
        days = min(max(int(match.group(1)), 1), 367)
        return today - timedelta(days=days - 1), today
    return today - timedelta(days=6), today


def _is_chart_request(text: str) -> bool:
    return any(word in text for word in ("图", "趋势图", "可视化", "柱状图", "饼图"))


def _demo_agent(
    db: Session, user_message: str, history: list[dict[str, str]]
) -> tuple[str, list[dict[str, Any]]]:
    previous_user = next(
        (item["content"] for item in reversed(history) if item["role"] == "user"), ""
    )
    is_follow_up = any(word in user_message for word in ("环比", "同比", "那呢", "这个呢"))
    context_message = previous_user if is_follow_up and previous_user else user_message
    effective_message = f"{context_message} {user_message}"
    lower = effective_message.lower()
    tool_calls: list[dict[str, Any]] = []

    def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            result = execute_tool(db, name, arguments)
            tool_calls.append({"name": name, "arguments": arguments, "result": result})
            return result
        except (ValueError, TypeError) as exc:
            tool_calls.append(
                {"name": name, "arguments": arguments, "error": str(exc)}
            )
            return {"error": str(exc)}
        except Exception:
            logger.exception("Demo agent tool execution failed: %s", name)
            tool_calls.append(
                {"name": name, "arguments": arguments, "error": "工具执行失败，请稍后重试。"}
            )
            return {"error": "工具执行失败，请稍后重试。"}

    if any(word in effective_message for word in ("库存", "还有多少", "剩多少")):
        product_match = re.search(
            r"(?:商品)?\s*([^，。？?！!：:]{2,30}?)(?:的)?(?:库存|还有多少|剩多少)",
            effective_message,
        )
        product_name = product_match.group(1).strip() if product_match else ""
        result = call_tool("query_stock", {"product_name": product_name})
        if "error" in result:
            return f"查询库存未完成：{result['error']}", tool_calls
        return f"{result['product_name']}当前库存为 {result['stock_quantity']} 件。", tool_calls

    wants_top = any(
        word in effective_message for word in ("热销", "畅销", "排行", "卖得最好", "销量最高", "top")
    )
    wants_chart = _is_chart_request(user_message)
    wants_notification = any(
        word in user_message for word in ("通知", "发给", "发到", "发送", "邮件", "群")
    )
    start_date, end_date = _resolve_period(effective_message)
    date_arguments = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }

    if wants_top or wants_chart:
        if wants_top:
            limit_match = re.search(
                r"(?:前\s*|top\s*|最高的\s*|最畅销的\s*)(\d{1,2})",
                lower,
                re.IGNORECASE,
            )
            limit = int(limit_match.group(1)) if limit_match else 5
            result = call_tool(
                "query_top_products", {**date_arguments, "limit": min(max(limit, 1), 20)}
            )
            if "error" in result:
                return f"商品排行查询未完成：{result['error']}", tool_calls
            products = result["products"]
            if not products:
                return "这个日期范围内没有查到商品销售记录。", tool_calls
            answer = (
                f"{start_date.isoformat()} 至 {end_date.isoformat()} 销量排行："
                + "；".join(
                    f"{index}. {item['name']}（{item['units_sold']} 件，销售额 ¥{item['sales_amount']:.2f}）"
                    for index, item in enumerate(products, 1)
                )
            )
            chart_labels = [item["name"] for item in products]
            chart_values = [item["units_sold"] for item in products]
        else:
            result = call_tool("query_sales", date_arguments)
            answer = (
                f"{start_date.isoformat()} 至 {end_date.isoformat()} 销售额为 "
                f"¥{result['sales_amount']:.2f}，共 {result['order_count']} 笔订单、"
                f"{result['units_sold']} 件商品。"
            )
            chart_labels = ["销售额", "订单数", "销售件数"]
            chart_values = [
                result["sales_amount"],
                result["order_count"],
                result["units_sold"],
            ]
        if wants_chart:
            chart = call_tool(
                "generate_chart",
                {
                    "title": "商品销量排行" if wants_top else "销售概览",
                    "labels": chart_labels,
                    "values": chart_values,
                    "chart_type": "bar" if "柱" in user_message else "pie",
                },
            )
            if "error" in chart:
                answer += f"\n图表生成失败：{chart['error']}"
            else:
                answer += "\n图表已生成。"
        else:
            chart = None
        if wants_notification:
            channel = "email" if any(word in user_message for word in ("邮件", "邮箱")) else "wechat"
            notification = call_tool(
                "send_notification",
                {
                    "message": answer,
                    "channel": channel,
                },
            )
            if "error" not in notification:
                answer += "\n通知内容已写入演示日志；当前不会实际发送到外部渠道。"
        return answer, tool_calls

    if "环比" in user_message and previous_user:
        current_start, current_end = _resolve_period(previous_user)
        duration = (current_end - current_start).days + 1
        previous_end = current_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=duration - 1)
        current = call_tool(
            "query_sales",
            {"start_date": current_start.isoformat(), "end_date": current_end.isoformat()},
        )
        previous = call_tool(
            "query_sales",
            {"start_date": previous_start.isoformat(), "end_date": previous_end.isoformat()},
        )
        if "error" in current or "error" in previous:
            return "环比查询未完成，日期或数据查询发生错误。", tool_calls
        if previous["sales_amount"] == 0:
            return (
                f"本期销售额 ¥{current['sales_amount']:.2f}，上期没有销售记录，"
                "无法计算环比百分比。",
                tool_calls,
            )
        change = (
            (current["sales_amount"] - previous["sales_amount"])
            / previous["sales_amount"]
            * 100
        )
        return (
            f"{current_start.isoformat()} 至 {current_end.isoformat()} 销售额 "
            f"¥{current['sales_amount']:.2f}；上期（{previous_start.isoformat()} 至 "
            f"{previous_end.isoformat()}）为 ¥{previous['sales_amount']:.2f}，"
            f"环比{('上升' if change >= 0 else '下降')} {abs(change):.2f}%。",
            tool_calls,
        )

    if any(word in effective_message for word in ("销售", "销售额", "营业额", "业绩", "订单", "收入")):
        result = call_tool("query_sales", date_arguments)
        return (
            f"{start_date.isoformat()} 至 {end_date.isoformat()} 销售额为 "
            f"¥{result['sales_amount']:.2f}，共 {result['order_count']} 笔订单、"
            f"{result['units_sold']} 件商品。",
            tool_calls,
        )
    return (
        "我是智能运营助手演示模式，可以查询销售额、商品排行和库存，也能生成图表或记录通知。"
        "例如：“查上周销售额”或“把上周销量最高的 3 个商品画成柱状图并发群”。",
        tool_calls,
    )


def _parse_tool_arguments(raw_arguments: Any) -> dict[str, Any]:
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if isinstance(raw_arguments, str):
        parsed = json.loads(raw_arguments)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("模型提供的工具参数不是有效的 JSON 对象。")


async def run_agent(
    db: Session, user_message: str, history: list[dict[str, str]]
) -> dict[str, Any]:
    if not settings.llm_api_key:
        answer, tool_calls = _demo_agent(db, user_message, history)
        return {"answer": answer, "tool_calls": tool_calls, "mode": "demo"}

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history[-10:],
        {"role": "user", "content": user_message},
    ]
    tool_calls: list[dict[str, Any]] = []
    for step in range(settings.max_agent_steps):
        response = await chat_completion(messages)
        model_tool_calls = response.get("tool_calls") or []
        if not isinstance(model_tool_calls, list):
            raise LLMError("大模型返回了无法识别的工具调用，请重试。")
        if not model_tool_calls:
            answer = response.get("content")
            if not isinstance(answer, str) or not answer.strip():
                raise LLMError("大模型没有返回回答内容，请重试。")
            return {"answer": answer.strip(), "tool_calls": tool_calls, "mode": "live"}

        if step == settings.max_agent_steps - 1:
            return {
                "answer": "任务执行步骤已达到上限，已停止继续调用工具。请缩小任务范围后重试。",
                "tool_calls": tool_calls,
                "mode": "live",
            }

        messages.append(
            {
                "role": "assistant",
                "content": response.get("content"),
                "tool_calls": model_tool_calls,
            }
        )
        for requested_call in model_tool_calls:
            if not isinstance(requested_call, dict):
                requested_call = {}
            function = requested_call.get("function", {})
            if not isinstance(function, dict):
                function = {}
            name = function.get("name", "")
            if not isinstance(name, str):
                name = ""
            raw_arguments = function.get("arguments", {})
            call_id = requested_call.get("id", name)
            if not isinstance(call_id, str):
                call_id = name
            try:
                arguments = _parse_tool_arguments(raw_arguments)
                result = execute_tool(db, name, arguments)
                tool_calls.append(
                    {"name": name, "arguments": arguments, "result": result}
                )
                tool_content = json.dumps(result, ensure_ascii=False)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                error_message = str(exc)
                logger.warning("Agent rejected tool call %s: %s", name, error_message)
                tool_calls.append(
                    {"name": name, "arguments": raw_arguments, "error": error_message}
                )
                tool_content = json.dumps({"error": error_message}, ensure_ascii=False)
            except Exception:
                logger.exception("Agent tool execution failed: %s", name)
                tool_calls.append(
                    {"name": name, "arguments": raw_arguments, "error": "工具执行失败，请稍后重试。"}
                )
                tool_content = json.dumps(
                    {"error": "工具执行失败，请检查参数或稍后重试。"},
                    ensure_ascii=False,
                )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": tool_content,
                }
            )
    return {
        "answer": "任务执行步骤已达到上限，已停止继续调用工具。请缩小任务范围后重试。",
        "tool_calls": tool_calls,
        "mode": "live",
    }

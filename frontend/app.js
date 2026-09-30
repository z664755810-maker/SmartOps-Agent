const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const messages = document.querySelector("#messages");
const chatArea = document.querySelector("#chat-area");
const welcome = document.querySelector("#welcome");
const sendButton = document.querySelector("#send-button");
const modeLabel = document.querySelector("#mode-label");
const sessionKey = "smartops-agent-session";

let sessionId = localStorage.getItem(sessionKey);
if (!sessionId) {
  sessionId = crypto.randomUUID();
  localStorage.setItem(sessionKey, sessionId);
}

document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    input.value = button.dataset.prompt;
    input.focus();
    resizeInput();
  });
});

input.addEventListener("input", resizeInput);
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

function resizeInput() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
}

function scrollToBottom() {
  chatArea.scrollTop = chatArea.scrollHeight;
}

function addMessage(role, text) {
  welcome.hidden = true;
  const wrapper = document.createElement("article");
  wrapper.className = `message ${role}`;
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "我" : "S";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  wrapper.append(avatar, bubble);
  messages.append(wrapper);
  scrollToBottom();
  return bubble;
}

function addLoading() {
  const bubble = addMessage("assistant", "");
  bubble.classList.add("loading");
  bubble.setAttribute("aria-label", "正在思考");
  bubble.innerHTML =
    '<span>正在分析并执行工具</span><span class="loading-dots"><span></span><span></span><span></span></span>';
  return bubble.closest(".message");
}

function addToolTrace(bubble, toolCalls) {
  if (!toolCalls.length) return;
  const trace = document.createElement("div");
  trace.className = "tool-trace";
  for (const call of toolCalls) {
    const row = document.createElement("div");
    row.className = "tool-row";
    const status = document.createElement("span");
    status.className = call.error ? "" : "tool-check";
    status.textContent = call.error ? "!" : "✓";
    const name = document.createElement("span");
    name.textContent = toolNames[call.name] || call.name;
    row.append(status, name);
    trace.append(row);
  }
  bubble.append(trace);
}

const toolNames = {
  query_sales: "查询销售数据",
  query_top_products: "查询商品销量排行",
  query_stock: "查询库存",
  generate_chart: "生成图表",
  send_notification: "记录通知",
};

const chartColors = ["#287654", "#54a47b", "#88c69e", "#b1dcb8", "#376b83", "#93b4bf"];

function addChart(bubble, chart) {
  if (!chart || !Array.isArray(chart.labels) || !Array.isArray(chart.values)) return;
  const card = document.createElement("section");
  card.className = "chart-card";
  const title = document.createElement("h4");
  title.className = "chart-title";
  title.textContent = chart.title;
  card.append(title);
  if (chart.chart_type === "pie") {
    const row = document.createElement("div");
    row.className = "pie-chart";
    const wheel = document.createElement("div");
    wheel.className = "pie-wheel";
    const total = chart.values.reduce((sum, value) => sum + value, 0);
    let angle = 0;
    const segments = chart.values.map((value, index) => {
      const start = angle;
      angle += total > 0 ? (value / total) * 360 : 0;
      return `${chartColors[index % chartColors.length]} ${start}deg ${angle}deg`;
    });
    wheel.style.background = total > 0
      ? `conic-gradient(${segments.join(", ")})`
      : "#edf2ee";
    const legend = document.createElement("div");
    legend.className = "pie-legend";
    chart.labels.forEach((label, index) => {
      const item = document.createElement("div");
      item.className = "legend-item";
      const dot = document.createElement("span");
      dot.className = "legend-dot";
      dot.style.background = chartColors[index % chartColors.length];
      const text = document.createElement("span");
      text.textContent = `${label} · ${chart.values[index]}`;
      item.append(dot, text);
      legend.append(item);
    });
    row.append(wheel, legend);
    card.append(row);
  } else {
    const rows = document.createElement("div");
    rows.className = "bar-chart";
    const max = Math.max(...chart.values, 1);
    chart.labels.forEach((label, index) => {
      const row = document.createElement("div");
      row.className = "bar-row";
      const labelElement = document.createElement("span");
      labelElement.className = "bar-label";
      labelElement.textContent = label;
      const track = document.createElement("span");
      track.className = "bar-track";
      const fill = document.createElement("span");
      fill.className = "bar-fill";
      fill.style.display = "block";
      fill.style.width = `${Math.max((chart.values[index] / max) * 100, 1)}%`;
      track.append(fill);
      const value = document.createElement("span");
      value.className = "bar-value";
      value.textContent = Number(chart.values[index]).toLocaleString("zh-CN");
      row.append(labelElement, track, value);
      rows.append(row);
    });
    card.append(rows);
  }
  bubble.append(card);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message || sendButton.disabled) return;

  addMessage("user", message);
  input.value = "";
  resizeInput();
  sendButton.disabled = true;
  const loading = addLoading();

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: sessionId }),
    });
    const result = await response.json();
    if (!response.ok) {
      const detail = typeof result.detail === "string" ? result.detail : "请求失败，请稍后重试。";
      throw new Error(detail);
    }
    sessionId = result.session_id;
    localStorage.setItem(sessionKey, sessionId);
    const bubble = loading.querySelector(".bubble");
    bubble.classList.remove("loading");
    bubble.removeAttribute("aria-label");
    bubble.textContent = result.answer;
    addToolTrace(bubble, result.tool_calls || []);
    addChart(bubble, result.chart);
    modeLabel.textContent = result.mode === "live" ? "大模型已连接" : "离线演示模式";
  } catch (error) {
    const bubble = loading.querySelector(".bubble");
    bubble.classList.remove("loading");
    bubble.textContent = `暂时无法完成请求：${error.message}`;
    modeLabel.textContent = "服务连接异常";
  } finally {
    sendButton.disabled = false;
    input.focus();
    scrollToBottom();
  }
});

fetch("/health")
  .then((response) => {
    if (!response.ok) throw new Error("服务状态异常");
    return response.json();
  })
  .then((health) => {
    modeLabel.textContent = health.llm_configured ? "大模型已连接" : "离线演示模式";
  })
  .catch(() => {
    modeLabel.textContent = "服务连接异常";
  });

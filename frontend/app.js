const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const messages = document.querySelector("#messages");
const assistantContent = document.querySelector("#assistant-content");
const welcome = document.querySelector("#welcome");
const sendButton = document.querySelector("#send-button");
const modeLabel = document.querySelector("#mode-label");
const historyList = document.querySelector("#history-list");
const sessionKey = "smartops-agent-session";
const chartColors = ["#287654", "#54a47b", "#88c69e", "#b1dcb8", "#376b83", "#93b4bf"];

let sessionId = localStorage.getItem(sessionKey);
let currentView = "dashboard";
let dashboardDays = 7;
let productSearchTimer;

const viewTitles = {
  dashboard: ["WORKSPACE / OVERVIEW", "经营概览"],
  assistant: ["WORKSPACE / AGENT", "运营 Agent"],
  products: ["WORKSPACE / INVENTORY", "商品与库存"],
};

const toolNames = {
  query_sales: "查询销售表现",
  query_sales_trend: "分析销售趋势",
  query_top_products: "查询商品排行",
  query_stock: "查询库存",
  list_products: "筛选商品库存",
  generate_chart: "生成可视化图表",
  send_notification: "生成通知摘要",
};

function api(path, options) {
  return fetch(path, options).then(async (response) => {
    const result = await response.json();
    if (!response.ok) {
      throw new Error(typeof result.detail === "string" ? result.detail : "请求失败，请稍后重试。");
    }
    return result;
  });
}

function escapeText(value) {
  return String(value ?? "");
}

function resizeInput() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
}

function scrollToBottom() {
  assistantContent.scrollTop = assistantContent.scrollHeight;
}

function setView(view) {
  if (!viewTitles[view]) return;
  currentView = view;
  document.querySelectorAll(".view-panel").forEach((panel) => {
    const active = panel.id === `${view}-view`;
    panel.hidden = !active;
    panel.classList.toggle("active", active);
  });
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  const [eyebrow, title] = viewTitles[view];
  document.querySelector("#page-eyebrow").textContent = eyebrow;
  document.querySelector("#page-title").textContent = title;
  document.querySelector("#period-label").hidden = view !== "dashboard";
  if (view === "dashboard") loadDashboard(dashboardDays);
  if (view === "products") loadProducts();
  if (view === "assistant") {
    input.focus();
    scrollToBottom();
  }
}

function addMessage(role, text, metadata = {}) {
  welcome.hidden = true;
  const wrapper = document.createElement("article");
  wrapper.className = `message ${role}`;
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "我" : "S";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = escapeText(text);
  wrapper.append(avatar, bubble);
  messages.append(wrapper);
  if (role === "assistant") {
    addToolTrace(bubble, metadata.tool_calls || []);
    addChart(bubble, metadata.chart);
    if (metadata.mode) addModeBadge(bubble, metadata.mode);
  }
  return { wrapper, bubble };
}

function addLoading() {
  const { wrapper, bubble } = addMessage("assistant", "");
  bubble.classList.add("loading");
  bubble.setAttribute("aria-label", "正在执行任务");
  const label = document.createElement("span");
  label.textContent = "正在分析请求并执行数据工具";
  const dots = document.createElement("span");
  dots.className = "loading-dots";
  for (let index = 0; index < 3; index += 1) {
    dots.append(document.createElement("span"));
  }
  bubble.append(label, dots);
  return wrapper;
}

function toolSummary(call) {
  if (call.error) return call.error;
  const result = call.result || {};
  if (call.name === "query_sales") {
    return `销售额 ¥${Number(result.sales_amount || 0).toLocaleString("zh-CN")} · ${result.order_count || 0} 笔订单`;
  }
  if (call.name === "query_top_products") {
    return `${(result.products || []).length} 个商品 · ${result.start_date || ""} 至 ${result.end_date || ""}`;
  }
  if (call.name === "query_sales_trend") {
    return `读取 ${(result.trend || []).length} 天逐日数据`;
  }
  if (call.name === "query_stock") {
    return `${result.product_name || ""} · 库存 ${result.stock_quantity ?? 0} 件`;
  }
  if (call.name === "list_products") {
    return `找到 ${(result.products || []).length} 个匹配商品`;
  }
  if (call.name === "generate_chart") {
    return `${result.title || "图表"} · ${(result.labels || []).length} 个数据点`;
  }
  if (call.name === "send_notification") {
    return result.status === "simulated" ? "摘要已写入本地演示通知日志" : "通知流程完成";
  }
  return "工具已执行";
}

function addToolTrace(bubble, toolCalls) {
  if (!toolCalls.length) return;
  const details = document.createElement("details");
  details.className = "tool-trace";
  const summary = document.createElement("summary");
  summary.textContent = `查看执行过程 · ${toolCalls.length} 个工具`;
  const list = document.createElement("div");
  list.className = "tool-list";
  toolCalls.forEach((call, index) => {
    const row = document.createElement("div");
    row.className = "tool-row";
    const marker = document.createElement("span");
    marker.className = call.error ? "tool-error" : "tool-check";
    marker.textContent = call.error ? "!" : String(index + 1).padStart(2, "0");
    const content = document.createElement("div");
    content.className = "tool-row-content";
    const name = document.createElement("b");
    name.textContent = toolNames[call.name] || call.name;
    const result = document.createElement("small");
    result.textContent = toolSummary(call);
    content.append(name, result);
    row.append(marker, content);
    list.append(row);
  });
  details.append(summary, list);
  bubble.append(details);
}

function addModeBadge(bubble, mode) {
  const badge = document.createElement("span");
  badge.className = `mode-pill ${mode === "live" ? "live" : ""}`;
  badge.textContent = mode === "live" ? "模型工具调用" : "演示模式 · 确定性数据工具";
  bubble.append(badge);
}

function addChart(bubble, chart) {
  if (!chart || !Array.isArray(chart.labels) || !Array.isArray(chart.values)) return;
  const card = document.createElement("section");
  card.className = "chart-card";
  const title = document.createElement("h4");
  title.className = "chart-title";
  title.textContent = chart.title;
  card.append(title);
  if (chart.chart_type === "pie") {
    addPieChart(card, chart);
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

function addPieChart(card, chart) {
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
  wheel.style.background = total > 0 ? `conic-gradient(${segments.join(", ")})` : "#edf2ee";
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
}

async function submitPrompt(prompt, navigate = false) {
  input.value = prompt;
  resizeInput();
  if (navigate) setView("assistant");
  await sendMessage();
}

async function sendMessage() {
  const message = input.value.trim();
  if (!message || sendButton.disabled) return;
  setView("assistant");
  addMessage("user", message);
  input.value = "";
  resizeInput();
  sendButton.disabled = true;
  const loading = addLoading();

  try {
    const result = await api("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: sessionId }),
    });
    sessionId = result.session_id;
    localStorage.setItem(sessionKey, sessionId);
    const bubble = loading.querySelector(".bubble");
    bubble.classList.remove("loading");
    bubble.removeAttribute("aria-label");
    bubble.textContent = result.answer;
    addToolTrace(bubble, result.tool_calls || []);
    addChart(bubble, result.chart);
    addModeBadge(bubble, result.mode);
    modeLabel.textContent = result.mode === "live" ? "大模型已连接" : "离线演示模式";
    await loadSessions();
  } catch (error) {
    const bubble = loading.querySelector(".bubble");
    bubble.classList.remove("loading");
    bubble.textContent = `任务未完成：${error.message}`;
    modeLabel.textContent = "服务连接异常";
  } finally {
    sendButton.disabled = false;
    input.focus();
    scrollToBottom();
  }
}

function renderSessionMessages(conversation) {
  messages.replaceChildren();
  const entries = conversation.messages || [];
  welcome.hidden = entries.length > 0;
  entries.forEach((item) => {
    if (item.role === "user") {
      addMessage("user", item.content);
    } else if (item.role === "assistant") {
      addMessage("assistant", item.content, item);
    }
  });
  welcome.hidden = entries.length > 0;
  scrollToBottom();
}

async function openSession(id) {
  try {
    const conversation = await api(`/api/sessions/${encodeURIComponent(id)}`);
    sessionId = conversation.session_id;
    localStorage.setItem(sessionKey, sessionId);
    renderSessionMessages(conversation);
    setView("assistant");
    await loadSessions();
  } catch (error) {
    if (error.message.includes("找不到")) {
      if (sessionId === id) startNewChat();
      await loadSessions();
      return;
    }
    modeLabel.textContent = `会话加载失败：${error.message}`;
  }
}

function startNewChat() {
  sessionId = null;
  localStorage.removeItem(sessionKey);
  messages.replaceChildren();
  welcome.hidden = false;
  setView("assistant");
  input.value = "";
  resizeInput();
  input.focus();
}

function renderHistory(sessions) {
  historyList.replaceChildren();
  document.querySelector("#history-count").textContent = String(sessions.length);
  if (!sessions.length) {
    const empty = document.createElement("p");
    empty.className = "history-empty";
    empty.textContent = "发送第一条消息后，对话会保存在这里";
    historyList.append(empty);
    return;
  }
  sessions.forEach((session) => {
    const item = document.createElement("div");
    item.className = `history-item ${session.session_id === sessionId ? "selected" : ""}`;
    const open = document.createElement("button");
    open.className = "history-open";
    open.type = "button";
    open.title = session.preview;
    const title = document.createElement("span");
    title.className = "history-title";
    title.textContent = session.title;
    const preview = document.createElement("small");
    preview.textContent = session.preview || "开始一段业务对话";
    open.append(title, preview);
    open.addEventListener("click", () => openSession(session.session_id));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "history-delete";
    remove.textContent = "×";
    remove.title = "删除这段对话";
    remove.setAttribute("aria-label", `删除对话：${session.title}`);
    remove.addEventListener("click", () => removeSession(session.session_id));
    item.append(open, remove);
    historyList.append(item);
  });
}

async function loadSessions() {
  try {
    const result = await api("/api/sessions");
    renderHistory(result.sessions);
  } catch (error) {
    historyList.textContent = `历史加载失败：${error.message}`;
  }
}

async function removeSession(id) {
  if (!window.confirm("删除这段对话？此操作无法撤销。")) return;
  try {
    await api(`/api/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (sessionId === id) startNewChat();
    await loadSessions();
  } catch (error) {
    modeLabel.textContent = `删除失败：${error.message}`;
  }
}

function formatCurrency(value) {
  return `¥${Number(value || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function renderKpis(data) {
  const { kpis } = data;
  const change = kpis.sales_change_percent;
  const cards = [
    {
      label: "销售额",
      value: formatCurrency(kpis.sales_amount),
      note: change === null ? "暂无上期数据可比较" : `较上期 ${change >= 0 ? "↑" : "↓"} ${Math.abs(change)}%`,
      icon: "↗",
      tone: change !== null && change < 0 ? "negative" : "positive",
    },
    { label: "完成订单", value: Number(kpis.order_count).toLocaleString("zh-CN"), note: `售出 ${kpis.units_sold} 件商品`, icon: "▤" },
    { label: "平均客单价", value: formatCurrency(kpis.average_order_value), note: "销售额 ÷ 订单数", icon: "◎" },
    { label: "库存预警", value: `${kpis.low_stock_count} 件`, note: `商品总数 ${kpis.product_count} · < 20 件`, icon: "!", tone: kpis.low_stock_count ? "warning" : "positive" },
  ];
  const grid = document.querySelector("#kpi-grid");
  grid.replaceChildren();
  cards.forEach((card) => {
    const element = document.createElement("article");
    element.className = "kpi-card";
    const top = document.createElement("div");
    top.className = "kpi-top";
    const label = document.createElement("span");
    label.textContent = card.label;
    const icon = document.createElement("span");
    icon.className = `kpi-icon ${card.tone || ""}`;
    icon.textContent = card.icon;
    top.append(label, icon);
    const value = document.createElement("strong");
    value.className = "kpi-value";
    value.textContent = card.value;
    const note = document.createElement("small");
    note.className = `kpi-note ${card.tone || ""}`;
    note.textContent = card.note;
    element.append(top, value, note);
    grid.append(element);
  });
}

function renderTrend(trend) {
  const container = document.querySelector("#sales-trend");
  container.replaceChildren();
  if (!trend.length) {
    container.textContent = "暂无趋势数据";
    return;
  }
  const width = 720;
  const height = 205;
  const padding = { top: 16, right: 18, bottom: 30, left: 12 };
  const values = trend.map((item) => item.sales_amount);
  const max = Math.max(...values, 1);
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const x = (index) => padding.left + (trend.length === 1 ? chartWidth / 2 : (index / (trend.length - 1)) * chartWidth);
  const y = (value) => padding.top + chartHeight - (value / max) * chartHeight;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "按天显示销售额变化的趋势图");
  [0, .5, 1].forEach((ratio) => {
    const line = document.createElementNS(svg.namespaceURI, "line");
    const lineY = padding.top + chartHeight * ratio;
    line.setAttribute("x1", String(padding.left));
    line.setAttribute("x2", String(width - padding.right));
    line.setAttribute("y1", String(lineY));
    line.setAttribute("y2", String(lineY));
    line.setAttribute("class", "chart-grid-line");
    svg.append(line);
  });
  const coordinates = trend.map((item, index) => `${x(index)},${y(item.sales_amount)}`).join(" ");
  const area = document.createElementNS(svg.namespaceURI, "polygon");
  area.setAttribute("points", `${padding.left},${padding.top + chartHeight} ${coordinates} ${width - padding.right},${padding.top + chartHeight}`);
  area.setAttribute("class", "trend-area");
  svg.append(area);
  const line = document.createElementNS(svg.namespaceURI, "polyline");
  line.setAttribute("points", coordinates);
  line.setAttribute("class", "trend-line");
  svg.append(line);
  const step = Math.max(1, Math.ceil(trend.length / 7));
  trend.forEach((item, index) => {
    if (index % step !== 0 && index !== trend.length - 1) return;
    const circle = document.createElementNS(svg.namespaceURI, "circle");
    circle.setAttribute("cx", String(x(index)));
    circle.setAttribute("cy", String(y(item.sales_amount)));
    circle.setAttribute("r", "4");
    circle.setAttribute("class", "trend-point");
    const title = document.createElementNS(svg.namespaceURI, "title");
    title.textContent = `${item.date} · ${formatCurrency(item.sales_amount)} · ${item.order_count} 单`;
    circle.append(title);
    svg.append(circle);
    const label = document.createElementNS(svg.namespaceURI, "text");
    label.setAttribute("x", String(x(index)));
    label.setAttribute("y", String(height - 7));
    label.setAttribute("text-anchor", index === 0 ? "start" : index === trend.length - 1 ? "end" : "middle");
    label.setAttribute("class", "chart-date-label");
    label.textContent = item.date.slice(5);
    svg.append(label);
  });
  container.append(svg);
  const totals = document.createElement("div");
  totals.className = "trend-total";
  totals.textContent = `期间合计 ${formatCurrency(values.reduce((sum, value) => sum + value, 0))}`;
  container.append(totals);
}

function renderRanking(products) {
  const list = document.querySelector("#top-products");
  list.replaceChildren();
  if (!products.length) {
    list.textContent = "当前时间范围暂无销售记录";
    return;
  }
  const max = Math.max(...products.map((item) => item.units_sold), 1);
  products.forEach((product, index) => {
    const row = document.createElement("div");
    row.className = "rank-row";
    const rank = document.createElement("span");
    rank.className = `rank-number ${index < 3 ? "top-rank" : ""}`;
    rank.textContent = String(index + 1).padStart(2, "0");
    const details = document.createElement("div");
    details.className = "rank-details";
    const name = document.createElement("div");
    name.className = "rank-name";
    name.textContent = product.name;
    const track = document.createElement("div");
    track.className = "rank-track";
    const fill = document.createElement("span");
    fill.style.width = `${Math.max((product.units_sold / max) * 100, 2)}%`;
    track.append(fill);
    details.append(name, track);
    const quantity = document.createElement("span");
    quantity.className = "rank-quantity";
    quantity.textContent = `${product.units_sold} 件`;
    row.append(rank, details, quantity);
    list.append(row);
  });
}

function renderLowStock(products) {
  const list = document.querySelector("#low-stock-list");
  list.replaceChildren();
  if (!products.length) {
    list.textContent = "库存充足，没有低库存商品。";
    return;
  }
  products.slice(0, 5).forEach((product) => {
    const row = document.createElement("div");
    row.className = "stock-row";
    const name = document.createElement("span");
    name.textContent = product.name;
    const stock = document.createElement("span");
    stock.className = "stock-badge";
    stock.textContent = `${product.stock_quantity} 件`;
    row.append(name, stock);
    list.append(row);
  });
  const link = document.createElement("button");
  link.className = "text-button stock-more";
  link.type = "button";
  link.textContent = "查看全部商品 →";
  link.dataset.view = "products";
  list.append(link);
}

function renderNotifications(notifications) {
  const list = document.querySelector("#notification-list");
  list.replaceChildren();
  if (!notifications.length) {
    const empty = document.createElement("p");
    empty.className = "notification-empty";
    empty.textContent = "还没有通知记录。可以在 Agent 中查询数据并生成通知摘要。";
    list.append(empty);
    return;
  }
  notifications.forEach((notification) => {
    const row = document.createElement("article");
    row.className = "notification-row";
    const icon = document.createElement("span");
    icon.className = "notification-icon";
    icon.textContent = notification.channel === "email" ? "✉" : "◎";
    const content = document.createElement("div");
    content.className = "notification-content";
    const heading = document.createElement("div");
    heading.className = "notification-heading";
    const channel = document.createElement("b");
    channel.textContent = notification.channel === "email" ? "邮件摘要" : "企业微信摘要";
    const timestamp = document.createElement("time");
    timestamp.dateTime = notification.created_at;
    timestamp.textContent = new Date(notification.created_at).toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
    heading.append(channel, timestamp);
    const message = document.createElement("p");
    message.textContent = notification.message;
    content.append(heading, message);
    const status = document.createElement("span");
    status.className = "notification-status";
    status.textContent = "已记录";
    row.append(icon, content, status);
    list.append(row);
  });
}

async function loadDashboard(days = dashboardDays) {
  dashboardDays = days;
  document.querySelector("#period-label").textContent = `近 ${days} 天 · 演示数据`;
  document.querySelectorAll(".period-switch button").forEach((button) => {
    button.classList.toggle("selected", Number(button.dataset.days) === days);
  });
  try {
    const result = await api(`/api/dashboard?days=${days}`);
    renderKpis(result);
    renderTrend(result.trend);
    renderRanking(result.top_products);
    renderLowStock(result.low_stock_products);
    renderNotifications(result.recent_notifications);
  } catch (error) {
    document.querySelector("#kpi-grid").textContent = `经营数据加载失败：${error.message}`;
  }
}

async function loadProducts() {
  const tbody = document.querySelector("#product-rows");
  const params = new URLSearchParams({ limit: "100" });
  const search = document.querySelector("#product-search").value.trim();
  const category = document.querySelector("#category-filter").value;
  const lowStock = document.querySelector("#low-stock-filter").checked;
  if (search) params.set("search", search);
  if (category) params.set("category", category);
  if (lowStock) params.set("low_stock_below", "20");
  tbody.innerHTML = '<tr><td colspan="5" class="table-empty">正在读取商品…</td></tr>';
  try {
    const result = await api(`/api/products?${params}`);
    tbody.replaceChildren();
    result.categories.forEach((item) => {
      if ([...document.querySelector("#category-filter").options].some((option) => option.value === item)) return;
      const option = document.createElement("option");
      option.value = item;
      option.textContent = item;
      document.querySelector("#category-filter").append(option);
    });
    result.products.forEach((product) => {
      const row = document.createElement("tr");
      const name = document.createElement("td");
      name.className = "product-name-cell";
      name.textContent = product.name;
      const categoryCell = document.createElement("td");
      categoryCell.textContent = product.category;
      const price = document.createElement("td");
      price.textContent = formatCurrency(product.price);
      const stock = document.createElement("td");
      stock.textContent = `${product.stock_quantity} 件`;
      const status = document.createElement("td");
      const badge = document.createElement("span");
      badge.className = `inventory-status ${product.low_stock ? "low" : "normal"}`;
      badge.textContent = product.low_stock ? "需要补货" : "库存正常";
      status.append(badge);
      row.append(name, categoryCell, price, stock, status);
      tbody.append(row);
    });
    if (!result.products.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 5;
      cell.className = "table-empty";
      cell.textContent = "没有找到符合条件的商品";
      row.append(cell);
      tbody.append(row);
    }
    document.querySelector("#product-count").textContent = `共 ${result.count} 件商品`;
  } catch (error) {
    tbody.innerHTML = "";
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 5;
    cell.className = "table-empty error-text";
    cell.textContent = `商品加载失败：${error.message}`;
    row.append(cell);
    tbody.append(row);
  }
}

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => {
    if (button.dataset.prompt) {
      submitPrompt(button.dataset.prompt, true);
      return;
    }
    setView(button.dataset.view);
  });
});

document.querySelector("#brand-home").addEventListener("click", () => setView("dashboard"));
document.querySelector("#new-chat-button").addEventListener("click", startNewChat);
document.querySelectorAll(".period-switch button").forEach((button) => {
  button.addEventListener("click", () => loadDashboard(Number(button.dataset.days)));
});
document.querySelectorAll("[data-prompt]:not([data-view])").forEach((button) => {
  button.addEventListener("click", () => submitPrompt(button.dataset.prompt, true));
});
form.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage();
});
input.addEventListener("input", resizeInput);
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});
document.querySelector("#product-search").addEventListener("input", () => {
  clearTimeout(productSearchTimer);
  productSearchTimer = setTimeout(loadProducts, 220);
});
document.querySelector("#category-filter").addEventListener("change", loadProducts);
document.querySelector("#low-stock-filter").addEventListener("change", loadProducts);

async function initialize() {
  const storedSession = sessionId;
  const healthPromise = api("/health").then((health) => {
    modeLabel.textContent = health.llm_configured ? "大模型工具调用已连接" : "免费演示模式";
  }).catch(() => {
    modeLabel.textContent = "服务连接异常";
  });
  await Promise.all([healthPromise, loadDashboard(), loadProducts(), loadSessions()]);
  if (storedSession) {
    try {
      const conversation = await api(`/api/sessions/${encodeURIComponent(storedSession)}`);
      renderSessionMessages(conversation);
      setView("assistant");
    } catch {
      sessionId = null;
      localStorage.removeItem(sessionKey);
      welcome.hidden = false;
      messages.replaceChildren();
    }
  } else {
    welcome.hidden = false;
  }
}

initialize();

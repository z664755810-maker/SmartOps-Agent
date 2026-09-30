# 智能运营助手 Agent

一个面向中小业务团队的自然语言运营助手。用户用一句话查询销售与库存、生成图表、记录通知；Agent 使用 Function Calling 选择业务工具，并以有上限的 ReAct 循环逐步执行。

> 默认演示数据为本地生成的模拟订单。未配置模型密钥时，应用会明确进入规则驱动的演示模式；配置兼容 OpenAI Chat Completions 的模型服务后，启用真实 Function Calling。通知只记入数据库日志，不会真的发邮件或企业微信。

## 解决的问题

- 业务人员在多个页面手工找销售、排行和库存，临时汇总、画图、发通知步骤繁琐。
- 把所有业务意图写成 `if/else` 路由会让每次新增动作都改动主流程。
- 直接让模型回答经营数据会有编造风险；单次工具调用也不能可靠完成“查询 → 生成图表 → 通知”的组合任务。

这里把可审计的数据操作封装为独立工具。销售查询与商品排行只访问 SQLAlchemy 数据库；模型通过函数描述选择工具，不能直接执行 SQL。服务端验证参数、限制循环步数、向模型反馈工具错误，并保留最近 5 轮对话，支持“上周销售额”后接着问“那环比呢”。

## 功能

| 工具 | 能力 |
| --- | --- |
| `query_sales` | 按含首尾日期统计销售额、订单数和售出件数 |
| `query_top_products` | 查询日期范围内销量排行，限制最多 20 个商品 |
| `query_stock` | 按名称查库存；名称不唯一或不存在时明确返回原因 |
| `generate_chart` | 生成经过校验的柱状图 / 饼图数据，并由前端绘制 |
| `send_notification` | 将邮件 / 企业微信通知写入日志，不调用真实外部渠道 |

首次启动会创建 20 个商品、每个商品的库存，以及最近 90 天内 200 条可复现的模拟订单。只在商品表为空时初始化数据，不会覆盖已有数据。

## 架构与执行流程

```text
浏览器聊天页
    │ POST /api/chat（会话 UUID、最近 5 轮历史）
    ▼
FastAPI ──► 模型 Chat Completions / Function Calling
    │                         │
    │                         └─ 选择工具与参数
    ▼
工具参数校验 ──► SQLAlchemy ──► SQLite
    │                                │
    └──── 工具结果 / 错误回传模型 ◄──┘
                     │
                     ▼
             最终回答 + 工具轨迹 + 图表
```

真实模型调用配置了最多 5 次模型迭代；请求失败返回明确的服务错误，不会悄悄切换到演示模式。对话以随机 UUID 关联，落在 SQLite 中，旧会话在应用启动时清理 30 天前记录。当前为单实例演示架构，不提供用户登录或多租户隔离。

## 本地运行

需要 Python 3.11+。Windows PowerShell 示例：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload
```

访问 <http://127.0.0.1:8000/> 打开聊天页，访问 `/docs` 查看 API。无需模型密钥即可体验演示模式；例如：

- `查一下上周销售额和订单数`
- `把上周销量最高的 3 个商品画成柱状图并发群`
- `无线鼠标现在还有多少库存？`
- 先问 `查上周销售额`，再追问 `那环比呢`

默认数据库在 `data/agent.db`。项目启动时会自动读取仓库根目录下被 Git 忽略的 `.env`；将 `.env.example` 复制为 `.env` 后填入模型供应商设置，即可启用真实 Function Calling。环境变量优先于 `.env` 中的同名配置。智谱示例：

```powershell
$env:LLM_API_KEY = "你的 API Key"
$env:LLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
$env:LLM_MODEL = "glm-4-flash"
python -m uvicorn app.main:app --app-dir backend --reload
```

也可将 `LLM_BASE_URL` 与 `LLM_MODEL` 指向支持 OpenAI 兼容工具调用的其他服务（例如阿里云百炼对应区域的兼容接口）。请在所用模型服务上确认模型具备工具调用能力；不要把真实密钥提交到代码仓库。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

测试覆盖日期边界与校验、库存歧义、图表输入校验、排行→图表→通知多工具链路、对话追问和请求校验。

## Docker 本地运行

```powershell
docker build -t smartops-agent .
docker run --rm -p 8000:8000 -v smartops-agent-data:/app/data smartops-agent
```

启用真实模型时通过 `-e LLM_API_KEY=...` 等方式注入环境变量。容器默认将 SQLite 放在 `/app/data/agent.db`；本地与生产均应挂载持久卷，避免重新部署后数据丢失。

Windows 上的 Docker Desktop 使用 WSL 2 后端。首次安装或启用 WSL 后若 `docker info` 提示 daemon 无法启动，请先重启 Windows，再打开 Docker Desktop 并运行 `docker info` 确认 Linux engine 已就绪。

## 部署

### 通过 GitHub Desktop 发布代码

1. 安装并打开 [GitHub Desktop](https://desktop.github.com/)，选择 **Sign in to GitHub.com**，在浏览器中登录并授权。
2. 在本项目根目录执行一次 `git init -b main`，然后在 GitHub Desktop 选择 **File → Add Local Repository…**，选择项目目录。
3. 确认变更列表没有 `.env`、`.venv`、`data/` 或数据库文件；这些内容已经加入 `.gitignore`。
4. 在左下角输入提交说明，例如 `Initial SmartOps Agent project`，选择 **Commit to main**，然后点击顶部 **Publish repository**。
5. 按需取消 **Keep this code private**（公开简历作品时才公开）。发布后记下 GitHub 仓库地址。

### Railway（推荐）

1. 在 GitHub Desktop 中将当前项目作为仓库发布到自己的 GitHub 账号。不要提交 `.env` 或 API Key。
2. 在 Railway 新建项目并从 GitHub 仓库部署，仓库根目录中的 `Dockerfile` / `railway.json` 会自动生效。
3. 在服务 Variables 中设置 `LLM_API_KEY`；需要真实模型时确认 `LLM_BASE_URL` 和 `LLM_MODEL`。不设置密钥也能使用演示模式。
4. 在服务设置中添加 Volume，挂载到 `/app/data`；设置 `DATABASE_URL=sqlite:////app/data/agent.db`。
5. 等待 `/health` 检查通过，在 Settings 中生成公开域名。更新简历前先用公网地址实际验证聊天与 `/docs`。

### Render

仓库也包含 `render.yaml`，可以由 GitHub 仓库直接连接：

1. 登录 [Render](https://render.com/) 后打开 Dashboard，选择 **New → Blueprint**。
2. 首次使用时授权 Render 访问 GitHub；选择 **Only select repositories** 并勾选刚发布的项目仓库。
3. Render 读取仓库根目录中的 `render.yaml`，确认服务名 `smartops-agent` 和资源计划后创建部署。
4. 部署过程中为 `LLM_API_KEY` 填入模型供应商的 API Key；不要将 Secret 写进 GitHub。确认 `DATABASE_URL` 为 `sqlite:////app/data/agent.db`。
5. 首次构建完成后打开服务 URL，检查首页和 `/health`，随后在简历中填写这个真实的 HTTPS 域名。
6. 后续通过 GitHub Desktop 提交并推送代码后，Render 会自动重新构建和部署。需要等待部署成功，再测试对话、图表和会话记忆。

当前 Blueprint 的 `starter` 实例与持久磁盘属于付费配置；这是为了让 SQLite 数据在重启和重新部署后保留。若改用没有持久磁盘的免费实例，应用可以运行演示，但本地 SQLite 数据和对话在实例重启 / 休眠后可能丢失，不建议把它描述成持久化的生产服务。

## 面试时可以展开

- 为什么由模型选工具，而不是让模型直接查数据库：函数边界让数据访问保持确定、可测试、可审计，LLM 只负责编排。
- ReAct 的边界：每次工具调用验证参数，错误作为结构化结果反馈模型；最大步骤数防止工具循环，供应商错误不会伪装成成功结果。
- 如何管理追问：SQLite 保存带 UUID 的对话摘要，模型上下文只携带最近 5 轮，而不是无界传入全部历史。
- 如何处理副作用：通知工具明确是模拟 outbox 记录；接入真实渠道时应加授权、幂等键、重试和审计，再由用户确认是否发送。
- 图表如何安全渲染：后端只接受有限长度的标签和有限非负数值，前端使用 DOM API 与文本节点绘制，不把模型输出当作 HTML 注入。

简历描述应以实际演示和测试结果为准，不要宣称真实渠道发送、生产多用户隔离或未实际测得的准确率 / 性能提升。

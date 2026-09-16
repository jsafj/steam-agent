# Steam 游戏畅销榜实时分析 Agent · V1

一个面向 **Steam Top Selling US** 的学习型 Python AI Agent。通过自然语言查询榜单，理解从网页爬取、确定性分析到 Tool Calling、RAG 和评测的完整流程。

LLM 负责选择工具和组织语言；实时事实来自 Steam，数值分析与关注标签由 Python 计算。Web 界面连续显示消息，但每个问题独立处理，没有多轮上下文记忆。

这是个人 AI Agent 学习项目，不是生产级系统，也不是 Steam 官方产品。开发过程中使用 AI Coding 工具辅助代码实现、测试与调试，结合离线测试与本地真实请求验证行为。

## 阅读导航

- 首次运行：[验证环境与依赖](#验证环境与依赖) → [从 clone 到运行 Web](#从-clone-到运行-web)。
- 遇到问题：[常见故障排查](#常见故障排查)。
- 理解实现：[核心能力与架构](#核心能力与架构)、[六个 Tools](#六个-tools)、[RAG](#rag)、[数据口径](#数据口径)。
- 检查效果：[测试与评测](#测试与评测)、[Known Limitations](#known-limitations)。

## 验证环境与依赖

- 当前本地验证环境：Windows / PowerShell、Python 3.12、SiliconFlow + `Qwen/Qwen3.5-4B`。
- RAG Embedding：SiliconFlow 的 `BAAI/bge-m3`，与聊天请求使用同一个 API Key。
- 聊天接口固定为 `https://api.siliconflow.cn/v1/chat/completions`；Embedding 接口固定为 `https://api.siliconflow.cn/v1/embeddings`。
- 请求通过 `requests` 发送，采用 OpenAI-compatible 消息格式；**不代表已验证其他 Provider 或模型兼容性**。当前没有多 Provider 配置或模型 fallback。
- 不需要本地 GPU、模型下载或数据库。需要能访问 Steam 与 SiliconFlow 的网络，以及有对应模型访问权限和可用额度的 SiliconFlow 账号。
- Python 依赖以 `requirements.txt` 为准，目前未锁定版本；不承诺所有 Python / 依赖版本均经过验证。

## 从 clone 到运行 Web

以下命令在 Windows PowerShell 中执行。先安装 Git 与 Python 3.12，并确保终端能找到它们。

### 1. 获取项目

在 GitHub 本仓库的 **Code → HTTPS** 中复制地址，替换下面的占位内容。`<仓库 HTTPS 地址>` 不是可直接使用的真实地址。

```powershell
git clone "<仓库 HTTPS 地址>" steam-agent
cd steam-agent
python --version
```

确认 Python 为 3.12；若安装了多个版本，可用 Windows Python Launcher 的 `py -3.12` 创建下一步的环境。

### 2. 创建虚拟环境并安装依赖

虚拟环境将本项目依赖与其他 Python 项目分开。以下命令均在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

全部依赖通过这一个文件安装；当前项目直接用 `requests` 调用 API，不需要另装 OpenAI SDK、Node.js 或前端构建工具，也不需要安装 Agent 框架。

每次打开新终端后，先进入项目目录并重新激活。若 PowerShell 不允许执行激活脚本，无须更改系统执行策略，可直接使用虚拟环境中的 Python：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

这种方式下，后文所有 `python` 都替换为 `.\.venv\Scripts\python.exe`。

### 3. 自行申请 SiliconFlow API Key

1. 打开 [SiliconFlow 控制台](https://cloud.siliconflow.cn)，自行注册或登录。
2. 进入 [API 密钥管理](https://cloud.siliconflow.cn/account/ak)，选择“新建 API 密钥”，将密钥保存到自己的本地配置中。操作参考 [官方快速上手](https://docs.siliconflow.cn/docs/userguide/quickstart)。
3. 在控制台确认账号可以调用 `Qwen/Qwen3.5-4B` 和 `BAAI/bge-m3`，检查可用额度、权限及当前计费规则。本项目不提供共享 Key，也不保证 API 免费或持续可用。

### 4. 配置 `.env`

首次使用时复制配置模板；下面的命令不会覆盖已有 `.env`：

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

用本地编辑器打开项目根目录的 `.env`，将占位值替换为自己的真实 Key。模板内容只有：

```dotenv
SILICONFLOW_API_KEY=your_api_key_here
```

- `.env.example`：可提交的配置模板，只含占位值。
- `.env`：本地私有配置，不要分享、截图或提交真实 Key，也不要将其写进 Python、测试或 README。
- `.gitignore`：已忽略 `.env` 和 `.env.*`，仅保留 `.env.example`。提交前仍应检查变更；忽略规则不会自动取消已被 Git 跟踪的文件。

程序通过 `python-dotenv` 加载项目根目录 `.env`，再读取 `SILICONFLOW_API_KEY` 环境变量。**进程已有环境变量优先于 `.env`**，因此旧环境变量可能覆盖新配置。无需在 `.env` 中设置模型或 API 地址，当前代码没有这些配置项。修改 Key 后请重启服务。

### 5. 启动 Web

```powershell
python web_app.py
```

浏览器打开 [本地聊天页面](http://127.0.0.1:5000)。服务仅监听本机，关闭调试模式，适用于本地学习演示。终端按 Ctrl+C 停止。

保持终端运行，不要直接打开 `templates/index.html`。首页能打开只说明 Flask 与静态页面正常，发送问题并得到回答才会验证 Agent 和外部服务。

### 6. 提问并核对结果

点击示例问题只会填入输入框，仍需点击“发送”或按 Enter。可分别验证：

- 现在 Steam Top 5 是什么？
- 当前上涨最多的 3 个游戏有哪些？
- 哪些游戏值得关注？为什么？
- Weeks 是什么意思？
- 现在有哪些 New？New 是不是代表刚发行？

首次请求或检索可能较慢。API 访问权限、网络和使用额度以 SiliconFlow 账号为准；真实聊天和评测可能产生 API 使用量。项目不会自动切换模型。

对于实时数据回答，核对来源为 Steam Top Selling US、`region=US`、`fetched_at` 为本次获取时间，并与网页数据对照。提示词约束不能保证模型绝不犯错。

首次 Web 验收建议分别发送“现在 Steam Top 10 是什么？”和“Weeks 是什么意思？”。前者检查实时抓取与分析，后者检查知识检索；两者都收到正常回答，才覆盖这两条独立链路。`fetched_at` 使用 UTC（`+00:00`），与北京时间相差 8 小时是正常的，不应直接当作旧数据。

### 7. 下次启动与停止

打开 PowerShell，进入此前 clone 得到的项目目录后运行：

```powershell
.\.venv\Scripts\Activate.ps1
python web_app.py
```

也可跳过激活，直接运行：

```powershell
.\.venv\Scripts\python.exe web_app.py
```

再次访问 `http://127.0.0.1:5000`。无需每次重新申请 Key、复制 `.env` 或安装依赖；在服务终端按 Ctrl+C 停止后，才能在该终端继续执行其他命令。

## 常见故障排查

先看启动 Web 的终端：`[Web]` 记录接口状态，`[Agent]` / `[LLM]` / `[Tool]` / `[RAG]` 标明执行阶段，`[Perf]` 记录第一次 LLM、Steam Snapshot、RAG、第二次 LLM 及整个 Agent 的耗时（仅记录实际执行的阶段）。浏览器错误保持通用，具体原因看服务器日志。分享日志前检查并去除敏感信息，不分享 Key、Header 或 `.env`。

| 现象 | 检查方式 |
|---|---|
| 找不到 `python` / Python 版本不对 | 确认 Python 安装和终端路径；多版本环境可用 `py -3.12 -m venv .venv`，随后使用虚拟环境解释器 |
| 激活脚本被禁止 | 使用上文 `.\.venv\Scripts\python.exe` 方式，不必修改全局执行策略 |
| `ModuleNotFoundError` | 用运行项目的同一个 Python 执行 `python -m pip install -r requirements.txt`，确认已激活环境且位于项目目录 |
| 提示 Key 未配置 / 仍为占位值 | 确认文件名是 `.env` 而非 `.env.txt`，位于项目根目录；变量名正确且已替换占位值；检查是否有旧环境变量优先，之后重启服务 |
| HTTP 401 / 403 / 404 / 429 | 分别检查密钥有效性、账号和模型权限、指定模型可用性、限额或余额及调用频率；以控制台实际提示为准 |
| `WinError 10013`、连接失败或超时 | 检查当前运行环境的联网权限、防火墙、代理和服务可用性；不要以不断增大 timeout 代替定位原因 |
| Steam 获取或解析失败 | 运行 `python steam_tool.py` 单独检查；网络、页面结构或榜单完整性异常都会明确失败，不会读取旧 CSV 兜底 |
| RAG 检索失败 | 确认 `knowledge/` 下三份 Markdown 完整、UTF-8 可读，并确认 Embedding 模型权限和网络；普通聊天成功不等于 Embedding 成功 |
| 浏览器无法访问 / 5000 端口被占用 | 确认终端服务仍在运行，使用 `http://127.0.0.1:5000`；关闭先前启动的本项目服务再重启。该地址仅代表浏览器所在的本机 |
| 首页正常，发送后提示分析失败 | 查看终端失败阶段与 HTTP 状态；先做下面的单模块检查，再运行 CLI Agent。普通聊天成功不代表 Tool Calling 和最终回答均成功 |
| 长时间“正在分析” | 检查终端停在哪一步；当前不流式输出，多次外部请求和串行服务可能累积等待。返回首页只停止浏览器等待，不取消已运行的后端任务 |
| 前端仍显示旧样式或交互 | 刷新或强制刷新浏览器；Python 配置或代码变更后需手动重启，当前未开启 debug 自动重载 |

Web 日志中的 HTTP 状态与上游 SiliconFlow 状态不是同一层：`/api/chat` 成功为 200，JSON 或 message 不合法为 400，非 JSON 为 415，请求体超过 32 KiB 为 413，Agent 执行异常为 502。看到 Web 502 时，应继续查看 `[LLM]`、`[Tool]` 或 `[RAG]` 的阶段日志定位原因，不能直接认定 SiliconFlow 返回了 502。

当前请求超时为连接 / 读取：聊天 `(10, 120)` 秒，Steam `(10, 30)` 秒，Embedding `(10, 60)` 秒。它们是单次请求的连接与读取等待限制，**不是整个回答的总时限**；当前不自动重试。

必要时在项目根目录依次执行以下命令，定位哪一层失败。除离线测试外，这些入口会真实联网；聊天和检索会使用 API：

```powershell
python llm_client.py
python steam_tool.py
python rag.py "Weeks 是什么意思？"
python agent.py "现在 Steam Top 10 是什么？"
```

`llm_client.py` 验证普通聊天；`steam_tool.py` 打印本次 Snapshot 元信息和前 5 条；`rag.py` 验证 Embedding 与检索；`agent.py` 验证完整工具调用与最终回答。只想验证一次抓取加四类 Python 分析，可运行 `python main.py`，不需要 LLM API Key。

## 核心能力与架构

实时 Snapshot、Top N、上涨幅度、Weeks、New、固定关注信号、Tool Calling、RAG、多工具共用 Snapshot，以及 Eval / Badcase。

```text
用户 → Web UI → Flask → Agent / Qwen → Tool Calling
                                      ├─ Steam Tools → 实时 Snapshot → Python 分析
                                      └─ search_knowledge → Markdown → Embedding → 检索
                               所有工具结果 → Qwen → 最终回答 → Web UI
```

路由由 LLM Tool Calling 决定，没有关键词硬编码路由。提示词要求：字段含义 / 规则问题只检索知识，纯 Top N / 上涨榜 / New 列表 / Weeks 数值问题只使用必要的 Steam 工具，需要数据和解释的问题组合调用。模型仍可能漏选或误选工具，需要评测。

### Tool Calling 执行流程

1. `run_agent(user_message) -> str` 接收独立问题。第一次聊天请求发送 system / user 和全部六个工具定义，显式 `enable_thinking=False`。
2. 模型返回工具调用后，Python 先检查工具白名单、调用 ID 与参数，再顺序执行。一次模型回复可请求多个工具。
3. 第一个 Steam 工具实时抓取 Snapshot；本次其他 Steam 工具复用同一份。知识检索不触发 Steam 抓取。
4. 将 assistant 的 `tool_calls` 和对应 `tool_call_id` 的 tool 结果加入消息。第二次请求不发送六个工具定义，显式 `tool_choice="none"`、`enable_thinking=False`，只生成最终文本。

当前最多一轮工具执行、两次聊天请求；没有工具调用时直接校验并返回第一轮文本。工具失败会停止，不会用旧数据或模型记忆兜底。对当前数据必须调用工具的要求主要由提示词约束，并非所有自然语言场景都有程序级事实校验。

### Steam 实时 Snapshot 与 Python 分析

每次调用 `get_steam_ranking()` 都重新请求 [Steam Top Selling US](https://store.steampowered.com/charts/topselling/US)，返回 `source_url`、带 UTC 时区的 `fetched_at`、`region`、`count`、`games`。当前解析器严格校验顺序排列的 1–100 名；结构改变或关键字段异常会报错。函数不读写 CSV。

每次成功执行 Steam 工具的 `run_agent` 只获取一份 Snapshot，同次多个工具共用；下一次当前榜单查询重新获取，不跨问题缓存榜单。纯知识查询不抓榜单。

`analysis.py` 只使用传入 Snapshot，校验后返回记录副本，不联网、不修改输入。Top N 按排名升序；上涨榜只比较 `up` 幅度；Weeks 按数值降序；New 按标记筛选。上涨幅度或 Weeks 相同时按当前排名升序。`n` 必须为正整数，符合条件不足 N 条时只返回实际条数。

工具结果中的 `count` 保留整份 Snapshot 的条数，`returned_count` 才是本工具返回的 `games` 条数；例如 Top 10 不会把全部 100 条游戏发送给最终回答模型。

## 六个 Tools

| 工具 | 参数 | 职责 |
|---|---|---|
| `get_steam_top_games` | 可选正整数 `n`，默认 10 | 当前排名前 N |
| `get_steam_top_rising_games` | 可选正整数 `n`，默认 10 | 页面显示上涨幅度最大的前 N |
| `get_steam_long_running_games` | 可选正整数 `n`，默认 10 | 页面 Weeks 数值最高的前 N |
| `get_steam_new_games` | 无参数，`{}` | 页面标记 New 的全部条目 |
| `get_steam_games_to_watch` | 无参数，`{}` | 按固定规则生成全部游戏的关注标签与理由 |
| `search_knowledge` | 必填非空字符串 `query` | 检索项目字段口径、业务规则和回答规范，固定返回 Top 3 片段 |

模型只能选择白名单工具和允许的参数，不能执行任意代码、指定文件路径或修改规则。

## 关注信号规则

- `rank <= 20` → `top_rank`。
- `rank_direction == "up"` 且 `rank_change_value >= 10` → `strong_rise`。
- 两者满足 → `high`；只满足一个 → 对应等级；都不满足 → `normal`。
- Weeks 不参与判断。排序为 high、top_rank、strong_rise、normal，同类按当前排名升序。

这些是项目自定义可解释规则，不是 Steam 官方标准、购买建议或预测模型。LLM 不得自行修改 Python 标签。

## RAG

`knowledge/*.md → 按标题切 Chunk → BAAI/bge-m3 Embedding → 余弦相似度 → Top K`

知识库只包含项目口径，不包含实时榜单：`steam_metrics.md` 说明字段，`attention_rules.md` 说明关注规则，`answer_guidelines.md` 说明回答边界。Agent 的知识工具固定检索 Top 3，返回来源、标题、段落标题、正文和相似度。

使用普通 Python 计算相似度，同进程复用未变化的知识向量，文档改变后重建；重启进程会丢失缓存，查询本身仍需 Embedding 请求。不使用向量数据库，相似度不是置信度。

## 数据口径

| 字段 | 使用方式 |
|---|---|
| rank | Steam Top Selling US 当前页面排名，不推算销量件数 |
| rank_change | 页面显示变化，不推断昨天、上周或上一期的比较周期 |
| Weeks | 页面显示数值，不解释为连续上榜时间 |
| New | 页面标记，不解释为新发行或首次上榜 |
| fetched_at | 程序获取页面响应的时间，不是 Steam 官方更新时间 |
| price | 保留页面原始价格文本，不据此推断币种或进行价格分析 |

`rank`、`weeks_on_chart` 为整数；`rank_direction` 区分 `up / down / new / same / unknown`。`rank_change_value` 对 up / down 为正整数幅度，same 为 0，new / unknown 为 `None`；未知变化不会被自动当成无变化。V1 固定美国榜单，不混合或补造 Global 来源。

## Web UI

- Flask 提供首页与 `POST /api/chat`；输入 JSON 的 `message`，成功返回 `ok` 和 `answer`，错误返回通用 `error`，内部定位信息留在服务器终端。
- 原生 HTML / CSS / JavaScript；四个示例只填入输入框，Enter 发送、Shift+Enter 换行，并避免中文输入法确认文字时误发送。
- 请求期间禁用重复提交、显示“正在分析”；完成后恢复输入、聚焦并滚动到新回答，失败后恢复原问题以便重试。
- 左上角“返回首页”清空本页聊天、恢复欢迎和示例、清空输入；旧请求响应不会重新写入界面。但它不会取消服务器已经开始的 Agent 调用。
- 消息只在当前页面暂存；回答以纯文本显示，不执行模型返回的 HTML，不渲染完整 Markdown。

## 测试与评测

```powershell
python -m unittest -v
python evals/evaluator.py
```

第一条运行离线 mock 测试，不消耗 API，不代表真实模型效果。第二条是真实评测，会调用 API，按模型选择访问 Steam / Embedding。

安装依赖后即可运行离线测试，无需配置真实 Key；真实评测需要前文的 API 配置和网络。真实评测不是首次启动 Web 的必做步骤。

V1 最近一次离线测试记录为 **109 项通过**；以自己 checkout 后的实际执行结果为准。已有本地真实验证覆盖聊天、Steam 抓取、工具调用、RAG 及最终回答，但不保证不同网络、账号或服务时段下始终成功，也未承诺实际响应速度。

18 个 Eval Cases：实时工具 5 个、纯 RAG 5 个、混合 4 个、语义边界 4 个。检查工具选择、禁止工具、Snapshot 次数、RAG 使用和明显语义违规。复杂语义和数字仍需人工复核，不使用 AI Judge。

自动失败追加到 `evals/badcases.json`，不覆盖历史；完整结果保存到 `evals/report_*.json`。这些运行产物默认被 Git 忽略。没有公布未经真实评测的准确率。用法详见 [评测说明](evals/README.md)。

开发过程中记录过的真实 Badcase 包括：虚构 Global 来源、将单次 Snapshot 误解为无法实时刷新、因相似游戏名擅自解释重复或数据混乱。最终回答约束已针对这些情况加强，但仍需人工复核；被忽略的本地记录文件不保证随 clone 提供。Trace 保留工具请求与执行、抓取 / RAG 次数、答案及通用运行错误；评测报告可能含问题和回答，分享前应检查内容，不并发运行多个评测进程。

## 项目结构

```text
README.md              项目说明与运行指南
requirements.txt       Python 依赖
.env.example           API Key 占位模板
.env                   自行创建的本地配置，不提交
.gitignore             本地配置与运行产物忽略规则
web_app.py             Flask 页面和聊天接口
templates/index.html   原生 HTML 聊天页
static/                CSS 与 JavaScript
agent.py               六工具编排与 Trace
steam_tool.py          实时 Steam Snapshot
analysis.py            确定性分析和关注规则
llm_client.py          SiliconFlow 对话调用
rag.py                 独立知识检索
knowledge/             三份项目知识文档
evals/                 用例、评测程序与使用说明
test_*.py              离线测试
main.py                四类 Python 分析的命令行演示
爬取/                  最初的爬虫与旧 CSV，仅供学习对照
```

## 技术栈与阅读顺序

Python、Flask、requests、BeautifulSoup、python-dotenv、SiliconFlow、Qwen/Qwen3.5-4B、BAAI/bge-m3、原生 HTML/CSS/JavaScript、unittest。Pandas 供原始爬虫使用。

建议依次阅读 `steam_tool.py → analysis.py → llm_client.py → agent.py → rag.py → web_app.py`，结合对应测试理解。

## Known Limitations

- 固定 US 榜单，单 Agent，无历史趋势数据库、登录或长期会话记忆。
- 一轮工具执行，最多两次聊天模型请求；第二次仍请求工具时会报错。
- Web 只显示最终文本，不解析完整 Markdown，不展示系统提示或内部推理。刷新页面会清空聊天展示。
- 页面防止重复发送；本地服务串行处理请求，不面向公网生产部署。
- 页面变更、API 限制、模型漏选工具或违反口径均可能导致失败，需要真实验收与 Badcase 修复。
- API Key 在服务器本地使用；问题、工具结果和知识片段会按调用流程发送到 SiliconFlow，不是完全离线应用。
- 没有自动重试、流式回答或模型 fallback；性能日志只用于定位耗时，不能证明真实速度已经提升。
- 请配置自己的 Key 后从浏览器实际提问并核对来源、数字和字段口径。离线测试、单模块成功或他人的本地验证不能代替自己的 Web 全链路验收。

## Future Work（未实现）

以下仅为可能的学习方向，不是 V1 已有能力或交付承诺：MCP 工具协议、多 Agent 协作、多 Provider / 多模型适配、模型 fallback、历史榜单数据库与长期趋势分析、持久化聊天与多轮记忆，以及面向公网部署所需的认证和运行保障。

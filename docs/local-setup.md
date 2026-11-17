# 韩语课程经营调研助手

应用面向“竞品课程调研 + 自家课程检索 + 销售复盘”。保留**一个主 Agent、三个子 Agent**，主 Agent 负责规划与最终整合。

自家课程与销售均为**合成验证资料**；不能宣称服务过真实培训机构或产生真实销售提升。竞品仅在 `live` 模式通过 Tavily 搜索。`offline` 是明确标识的固定流程演示，不调用大模型，也不代表多 Agent 的推理效果。

## 已实现

| 角色 | 专属工具 | 负责的内容 |
|---|---|---|
| 主 Agent | DeepAgents 委派、任务规划 | 决定调查步骤，必要时补查，整合报告 |
| network | Tavily 联网搜索 | 竞品价格、授课方式、课时、服务和公开条件 |
| course | 现有 RAG 的内部 HTTP 检索接口 | 自家课程原文、章节、页码；不走销售对话链 |
| sales | 表结构、受限只读 SQL | MySQL 订单、收款、退款和渠道分析 |

任务、对话消息、执行事件、证据、报告索引落 SQLite；LangGraph 检查点单独持久化。页面采用GPT式对话：左侧会话、底部输入、多轮追问、缺失信息澄清、停止生成和来源折叠查看。深浅主题自动跟随系统设置，系统切换后即时生效。输入区只保留消息与发送按钮，课程、竞品和日期直接在对话中说明。默认只回答，不生成文件；回答后可按需导出Markdown / PDF，无需再次调用模型。设置任务时间、模型、工具及搜索次数上限，记录 Token 和可选费用估算。报告引用只能使用本次实际取得的证据 ID；引用内容是否支持结论仍需人工评测。

实际后端入口为 `korean.server:app`，前端入口为 `frontend/src/ResearchApp.tsx`（路径相对项目根目录）。旧教学代码和旧界面已归档，不参与运行；来源和实现边界见 [UPSTREAM.md](../UPSTREAM.md)。

Live模式支持真实流式回答：检索阶段显示进度，主Agent生成正文时通过SSE逐步更新Markdown。仅展示主Agent的文本，工具参数、模型推理字段和专家内部结果不作为回答展示。生成中的草稿会保存，断线自动重连，刷新可恢复；停止生成保留未完成草稿并明确标注，完成后才提供MD/PDF导出。离线模式使用固定流程，直接返回演示回答。

## 1. 先运行离线演示

环境：Windows PowerShell、Python 3.12、Node.js 20+、uv、pnpm。与 `local_rag` 使用**不同虚拟环境**，避免 DeepAgents / LangGraph 版本冲突。

Vite 7需要Node.js 20.19+或22.12+。PDF在Windows默认嵌入宋体；其他系统可用 `RESEARCH_PDF_FONT` 指向本机支持中文的可嵌入TTF/TTC文件。

```powershell
cd E:\智能对话Agent\deepsearch-korean
.\setup.ps1
.\start.ps1 -Offline
```

打开 <http://127.0.0.1:8000>，输入“对比K01和竞品的课程，竞品：离线示例机构”，点击发送或按Enter。课程、竞品和日期通过消息指定，缺少信息时会在对话中追问。回答后可导出文件。这个模式不需要 API Key、MySQL、Milvus 或运行中的 RAG。

当前对话范围解析为保守规则：支持课程ID/全名、“竞品：机构名”和两条ISO日期，不能理解所有自然语言日期或机构表达；无法确定时会追问。Live模式中的Agent负责回答内容，离线模式只展示按范围筛选的固定资料与SQL结果。

`setup.ps1` 使用 `uv.lock` 安装 Python 依赖、安装并构建前端、在缺失时从 `.env.example` 创建 `.env`，并生成销售数据。若不用 uv，可自行创建 Python 3.12 虚拟环境后安装 `requirements.txt`；该文件由 `uv.lock` 导出，包含开发测试依赖。

前后端开发可分开启动：后端使用上面的脚本，前端在 `frontend` 下执行 `pnpm dev`，设置 `frontend/.env.local` 中 `VITE_API_BASE_URL=http://127.0.0.1:8000`，访问 Vite 显示的地址。正式本地演示使用后端托管的构建产物即可。

## 2. 接入真实调用模式

在本项目 `.env` 配置以下字段，**不要提交密钥**：

```dotenv
RESEARCH_MODEL=你的支持工具调用的模型名称
OPENAI_BASE_URL=你的OpenAI兼容服务地址
OPENAI_API_KEY=你的模型密钥
TAVILY_API_KEY=你的搜索密钥
RAG_BASE_URL=http://127.0.0.1:8899
RAG_RESEARCH_TOKEN=自行生成的内部共享令牌
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3307
MYSQL_DATABASE=korean_sales_demo
MYSQL_USER=korean_reader
MYSQL_PASSWORD=demo-reader-change-me
```

### 接入已有 RAG

已在相邻 `local_rag` 增加 `POST /api/research/retrieve`。本机推荐使用独立只读网关，复用已有验证库，原销售对话服务可以继续运行。

在本项目目录执行一次配置连接（生成或复用共享令牌，更新两端 `.env`）：

```powershell
.\.venv\Scripts\python.exe scripts/connect_local_rag.py
```

然后在两个 PowerShell 窗口中分别启动：

```powershell
# 窗口一：课程资料只读网关，默认8899
.\start-rag-gateway.ps1
```

```powershell
# 窗口二：对话页面与Agent，默认8000
.\start.ps1
```

打开 <http://127.0.0.1:8000>，输入：**只查课程，K03适合什么基础的学员？是否适用于TOPIK II中高级备考？请简短回答并引用原文。** 回答后可按需导出 Markdown 或 PDF。

本机网关脚本使用 `E:/Python3127/python.exe` 和已存在的 `local_rag_agent_eval` MySQL库、`local_rag_eval_documents` Milvus集合及四份已发布的合成课程PDF；迁移电脑时需调整脚本路径并准备对应资料。网关只暴露课程检索和健康检查，不启动销售对话或导入工作流。配置连接不初始化这些数据库。

模型通过 `RESEARCH_MODEL_ENV_FILE` 引用现有 `local_rag/.env` 的 `DEEPSEEK_MODEL`、`DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`，无需复制模型密钥。显式配置的 `RESEARCH_MODEL`、`OPENAI_API_KEY`、`OPENAI_BASE_URL` 优先；使用文件引用时应将这三项留空，避免混用供应商配置。

也可使用原RAG服务的同名接口：两端分别配置相同的 `RESEARCH_TOKEN` / `RAG_RESEARCH_TOKEN`，将 `RAG_BASE_URL` 改成原服务地址，并重启原服务以加载令牌。

接口只读取已发布的课程资料，复用原检索与重排，返回原文片段、文档名、章节、页码、chunk ID 和检索状态；不调用销售回复、用户画像或客户动作。请求需要 `X-Research-Token`，未配置令牌时返回503。

```http
POST http://127.0.0.1:8899/api/research/retrieve
X-Research-Token: 与配置一致
Content-Type: application/json

{"course_id":"K01","query":"价格、课时与答疑政策","top_k":6}
```

当前课程 ID 必须与现有文档一致：K01零基础入门、K02日常交流、K03 TOPIK初级备考。K03对应 TOPIK I，不能在报告中改写成 TOPIK II。

连通性检查与一次真实Agent验收：

```powershell
# 两次真实检索，调用Embedding / Rerank服务
.\.venv\Scripts\python.exe scripts/check_rag_connection.py
# 一次真实模型任务，会产生模型及检索费用
.\.venv\Scripts\python.exe scripts/check_course_agent.py
```

结果保存到 `data/acceptance/`，包含原文证据与执行记录。已完成的真实联调及范围见 [rag-live-acceptance.md](rag-live-acceptance.md)。仅配置本节时请先使用“只查课程”；竞品搜索和销售MySQL需要分别配置。

### 先运行竞品与自家课程对比

无需等待销售数据库：在本项目 `.env` 配置 `TAVILY_API_KEY`，启动课程网关并重启调研服务。页面输入：

> 课程对比，自家K01，竞品：沪江网校。只比较韩语零基础课程的适用人群、教学方式、价格与课时，不查销售，找不到的字段写本次未检索到。

“课程对比”“只对比”“不查销售”进入 `comparison` 范围，只给主Agent开放network和course两个专家；销售工具不参与本次任务。完整三路调研使用“完整调研”或“综合调研”。搜索来源保留网页地址、采集时间及正文/搜索摘要类型，搜索摘要不保证反映当前售卖价格。

```powershell
# 一次真实搜索，不调用模型
.\.venv\Scripts\python.exe scripts/check_network_agent.py --search-only
# 一次真实主Agent → network/course → 对比回答
.\.venv\Scripts\python.exe scripts/check_network_agent.py --competitor '沪江网校'
```

检查会调用收费搜索/模型服务，记录保存在 `data/acceptance/`，不会自动反复提交任务。真实竞品信息与自家合成课程的对比只能用于功能展示。

已完成的一次真实协作及局限见 [network-live-acceptance.md](network-live-acceptance.md)。网页证据最多保存30000字符，返回模型前6000字符并注明截断；模型没读到的部分不能作为判断依据。

### 初始化独立销售 MySQL

本机已安装MySQL时，可以复用同一数据库服务，建立独立的 `korean_sales_demo` 库。当前电脑已按此方式配置（127.0.0.1:3306），不需要Docker。

```powershell
# 使用相邻local_rag/.env的本机管理员连接，仅用于初始化独立销售库
.\.venv\Scripts\python.exe scripts/connect_sales_mysql.py
# 18组真实MySQL统计对照 + 运行账号授权检查 + 无行UPDATE权限拒绝检查
.\.venv\Scripts\python.exe scripts/check_sales_connection.py
# 配置完成后重启调研服务
.\start.ps1
```

初始化脚本验证源文件SHA256、课程金额、日期与退款关联，导入1800条订单和103条退款，逐行核对数据库内容，建立查询索引。创建随机密码的专用账号 `korean_research_reader@127.0.0.1`，仅授予三张销售表的SELECT权限，将只读连接写入本项目 `.env`；不复制管理员凭据。再次执行只核对已有库，不覆盖数据。若目标库或账号已存在且没有本项目初始化记录，脚本拒绝接管。SQL DDL不支持事务回滚，初始化中途失败时保留现场，不自动删库重建。

页面可以输入“只查销售，K01在2026-08-01至2026-11-01的订单、收款和退款如何变化？”。统计按北京时间，结束日不计入区间。真实模型验收命令：

```powershell
# 先执行check_sales_connection.py生成独立参考记录
.\.venv\Scripts\python.exe scripts/check_business_agents.py
# 三路综合调研：network + course + sales
.\.venv\Scripts\python.exe scripts/check_business_agents.py --full
```

每条命令发送一次真实模型任务，会产生费用，不自动重跑。结果保存在 `data/acceptance/`，每次按task_id保留，数字需结合SQL与独立参考人工核对。

本机销售与三路真实协作已完成，结果和局限见 [sales-live-acceptance.md](sales-live-acceptance.md)。

若已安装 Docker：

```powershell
docker compose up -d mysql
```

容器仅映射本机3307，创建独立 `korean_sales_demo` 和仅有三张表 SELECT 权限的 `korean_reader`。演示管理员密码默认 `demo-admin-change-me`，可用 `MYSQL_ADMIN_PASSWORD` 环境变量覆盖；已有卷不会重新执行初始化脚本。也可在自己的 MySQL 上执行 `docker/sales-init.sql`，勿对原 RAG 数据库执行。

首次导入需临时使用**这个演示库**的管理员权限：

```powershell
$env:MYSQL_USER='root'
$env:MYSQL_PASSWORD='你的演示库管理员密码'
.\.venv\Scripts\python.exe scripts/sales_data.py --import-mysql
Remove-Item Env:MYSQL_USER
Remove-Item Env:MYSQL_PASSWORD
```

导入脚本只允许目标库名 `korean_sales_demo`，拒绝向非空目标表追加或覆盖。运行时从 `.env` 恢复只读账号，不使用管理员账号。

完成配置后：

```powershell
.\start.ps1
```

`GET /api/health` 的 configured 字段仅说明配置是否存在，不代表服务已连通。缺失单路来源会保留其他证据并标记 `PARTIAL`；无可用证据为 `FAILED`，不会自动切换到虚构资料。

## 3. 数据与统计口径

`scripts/sales_data.py` 用固定种子生成三门课程、1800条订单及退款，覆盖北京时间2026-05-01至2026-11-01（不含结束日）。不是当前真实经营数据，日期筛选必须在此范围内。

生成文件位于 `data/`：原始 JSON、SQLite 离线库、SHA256 来源清单、独立 Python Decimal 参考结果。退款发生在付款之后，允许跨月，不能将当月退款笔数直接除以当月订单数作为退款率。没有线索表、咨询人数及广告成本，因此不计算咨询转化率、ROI，也不能证明竞品导致销量变化。

- 成交订单和收款按付款时间；退款按实际退款时间。
- 区间净收款 = 区间收款 − 区间退款，不等于会计收入，可能为负。
- 成交客单价 = 收款 / 成交订单数，无订单时未知。
- SQL仅允许单条、限定三张表的 SELECT；禁止写入、跨库、文件操作、锁表与未批准函数。单查询5秒、最多500行，超量明确标记截断。

详细架构、统计与故障约定见 [architecture-korean.md](architecture-korean.md)。

## 4. 验证与评测

当前r13已完成 [回答收尾与冻结新题验收](answer-contract-acceptance.md)：句子级引语检查、固定句数约定、未知字段及检索状态交接；75项自动测试通过。6道新题一次执行，3题SUCCEEDED、3题PARTIAL；开发复核3题pass、3题needs_fix。仍有篇幅、未知范围与字面误报，不能称质量问题全部解决；以下各轮结果按历史版本分别保留。

最新已完成 [字段忠实度与网页归属修复](fact-fidelity.md)：新增星期保真、网页局部分段与竞品对象锚定，改进否定/答疑时效误报；69项自动测试通过。4题真实定向复测2题SUCCEEDED、2题PARTIAL，整份回答复核1题pass、3题needs_fix。原目标错误未复现，仍有引用、冗余和未知范围问题；不能代替完整15题或留出集验收。

固定15题开发验收集位于 `examples/acceptance_15.json`：12题真实模型调研、3题本地异常验证。已完成r8固定版本完整验收：真实任务5题SUCCEEDED、7题PARTIAL；逐项开发复核2题pass、8题needs_fix、2题fail；3题本地验证通过。执行成功与语义通过分别记录，详见 [最新完整验收](final-acceptance.md)，历史结果见 [固定15题验收](acceptance-15.md)。

求职材料入口：[三分钟演示与面试讲解](interview-demo.md)、[简历项目表述](resume-project.md)。自家课程与销售均为合成验证资料，不代表真实业务收益。

已接入 [结构化专家交接与短答](structured-handoff.md)：原子事实绑定对象、适用范围和原文摘录，销售数字直接交接工具表格；超长正文最多压缩一次，保持流式输出。该轮自动测试43项通过，真实3题复测仍有逐句引用与方式推断缺口，未宣称语义全通过。

后续已完成 [引用边界收尾](evidence-boundaries.md)：Q查询/M口径引用分离，方式与服务摘录检查，正文存在缺口时最多修订一次。当前49项自动测试通过；r8完整验收仍发现上课星期错误、竞品班型基础错配和字面检查误报，未宣称语义全通过。

```powershell
# 默认只跑本地异常，不调用付费模型
.\.venv\Scripts\python.exe scripts/acceptance_15.py
# 12次真实模型任务与3条本地验证，产生模型和搜索费用
.\.venv\Scripts\python.exe scripts/acceptance_15.py --mode all
```

月度统计使用 `sales_monthly` 保留空月及仅退款月，渠道成交/收款使用 `sales_channels`。自定义SQL仍需核对语义；引用编号有效不保证每句话都有原文支持。

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe scripts/evaluate.py --split dev
.\.venv\Scripts\python.exe scripts/evaluate.py --split holdout
```

50条固定评测任务在 `examples/eval_cases.json`：30条开发、20条留出，每类（销售、课程、网络、综合、缺失信息）均有覆盖。上面的 SQL 评测仅对其中销售/综合任务的统计组件与独立参考进行比较，**不是50条 Agent 语义准确率**。真实 DeepAgents 调度单元测试使用脚本模型，验证三个专家调用与预算，不能替代供应商联调。

真实模型的单 Agent / 多 Agent 对照需要运行中的 live 服务，会产生模型及搜索费用，建议先跑1例：

```powershell
.\.venv\Scripts\python.exe scripts/evaluate.py --live --split dev --limit 1 --competitors '实际机构名'
```

保存每次报告、证据、用量和待人工打分项，不伪造准确率。两组交替执行但联网结果会变化；当前未实现网络快照回放，因此这属于探索性比较，不能据此宣称严格控制变量的多 Agent 提升。留出集应在提示词和工具口径确定后再运行。验收记录和演示步骤见 [acceptance.md](acceptance.md)。

## 5. API 与运行边界

- `POST /api/task`：课程、1～3家竞品、日期、要求；返回 task_id 和 thread_id。`analysis_mode` 可选 multi / single，`research_scope` 可选 full / comparison / network / course / sales。
- `POST /api/chat`：message、可选thread_id和调研范围；缺失信息返回clarification，完整信息创建研究任务，同会话短追问继承上一轮范围。
- `GET /api/conversations`、`GET /api/conversations/{thread_id}`：会话列表、消息与本会话任务。
- `POST /api/tasks/{id}/export`：回答完成后传入format=markdown或pdf，按需生成并返回产物；重复导出复用文件。
- `GET /api/tasks`、`GET /api/tasks/{id}`、`/events`、`/evidence`：历史与证据。
- `GET /api/tasks/{id}/stream`：SSE；先发送带事件游标的任务snapshot，再发送answer_delta / answer_reset及进度update，完成时以最终snapshot替换草稿。重连重新读取一致性快照，避免重复拼接；草稿未经最终引用检查。
- `POST /api/task/{id}/cancel`：取消；重新提交相同请求会创建新任务，保留旧报告。
- `GET /api/download/{artifact_id}`：只下载已登记的本任务产物。
- `WS /ws/{thread_id}`：事件展示；HTTP持久化记录为恢复依据。
- 上传接口只保存附件，第一版不自动把附件纳入检索或报告。

`output_format` 支持none（默认）、markdown、pdf、both。pdf只生成PDF，both生成两种。旧任务与已生成的文件继续保留在数据存储中；新对话列表只显示通过chat接口创建的会话。

启动一个 Uvicorn worker，同时最多2个任务。默认单任务600秒、60次模型请求、40次工具、10次搜索。重启将未完成任务标记为中断，需手动新任务重试。费用未知时显示未知，模型估算费用不含搜索费。

这是本机学习及求职展示版本，尚未实现公网用户认证、租户隔离、队列分布式调度或真实业务效果验证。不要直接部署到公网，也不要在简历中填写未经测量的准确率或性能提升。

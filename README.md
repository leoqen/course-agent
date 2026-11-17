# 韩语课程经营调研 Agent

面向韩语课程运营与销售复盘的多 Agent 应用。用户在对话中提出问题，主 Agent 按范围委派联网、课程和销售专家，结合竞品网页、自家课程文档与交易记录回答，并保留本次证据和查询结果。

前端支持多轮追问、SSE 流式回答、停止生成、断线恢复，主题跟随系统。回答完成后可选择导出 Markdown 或 PDF，导出不再次调用模型。

## 工作流程

| 角色 | 工具与职责 |
|---|---|
| 主 Agent | 规划任务、按范围委派、整合回答；基于 DeepAgents / LangGraph |
| 联网专家 network | Tavily 搜索竞品，保存网页摘录与来源 |
| 课程专家 course | 调用现有 RAG 的只读 HTTP 接口，检索自家课程原文 |
| 销售专家 sales | 读取 MySQL 表结构，执行受限只读 SQL 与月度、渠道统计 |
| 对话服务 | 澄清请求、保存消息/事件/证据、控制预算、推送流式正文与导出文件 |

金额与退款走交易库，课程政策走原文，竞品信息走公开网页。销售变化只支持描述与比较；现有数据不能证明竞品导致销量变化。

## 本地启动

需要 Python 3.12、uv、pnpm 11.25，以及 Node.js 20.19+ 或 22.12+。

```powershell
.\setup.ps1
.\start.ps1 -Offline
```

打开 <http://127.0.0.1:8000>。离线模式使用固定合成资料，不调用模型。真实调用需配置本地 `.env`，并启动搜索、RAG 和 MySQL；详见 [安装与服务接入](docs/local-setup.md)。

## 代码导航

```text
korean/
  server.py         HTTP、任务生命周期、SSE 与文件接口
  runtime.py        主 Agent / 三个专家组装、回答整合与引用检查
  prompts.py        主 Agent 与专家提示词
  tools.py          搜索、课程检索、销售工具接入与证据登记
  budget.py         调用次数、耗时与 Token 预算
  streaming.py      主 Agent 正文流与草稿持久化
  handoff.py        专家结构化交接与有限回答约束
  web_context.py    网页分段、对象与上下文处理
  sales.py          只读 SQL 校验与销售统计
  conversation.py   对话范围解析与澄清
  store.py          SQLite 消息、任务、事件及证据
  models.py         请求和范围约束
  config.py         配置与课程标识
  pdf.py            PDF 导出
frontend/src/
  ResearchApp.tsx   会话切换、发送与 SSE 订阅
  api.ts            HTTP 客户端
  types.ts          页面数据类型
  status.ts         任务状态展示
  components/       回答、Markdown 与图标组件
scripts/            合成数据、独立统计参考与验收脚本
tests/              本地工程测试
examples/           课程样例与固定题集
docs/               架构、运行、验收与讲解材料
```

请求如何经过这些模块，见 [代码讲解](docs/code-guide.md)。旧教学后端、旧界面和教学示例已移至工作区研究目录，不参与运行。

## 验证与边界

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

工程测试 75 项通过，不等于 75 条真实问答正确。最近一轮冻结新题共 6 题：执行状态 3 题 SUCCEEDED、3 题 PARTIAL；开发复核 3 题 pass、3 题 needs_fix。详见 [回答约束验收](docs/answer-contract-acceptance.md)。本轮结构整理不构成新一轮真实模型验收。

自家课程与销售均为合成验证资料；离线模式是固定流程演示。当前适合本机学习与求职展示，尚无公网鉴权、租户隔离或分布式任务队列。来源编号与原文检查不能保证每句话语义正确，已有失败样例保留在验收记录中。

- [架构与统计口径](docs/architecture-korean.md)
- [本轮代码整理记录](docs/code-cleanup.md)
- [三分钟演示与面试讲解](docs/interview-demo.md)
- [简历项目表述](docs/resume-project.md)

## 来源

项目参考 [DeepSearch Agents](https://github.com/didilili/deepsearch-agents) 的调度思路，并沿用部分前端渲染代码。固定提交、沿用范围与本项目实现边界见 [UPSTREAM.md](UPSTREAM.md)。

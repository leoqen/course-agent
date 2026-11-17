# 来源与实现边界

参考项目：[didilili/deepsearch-agents](https://github.com/didilili/deepsearch-agents)。固定源码提交：`8263e95444fd7113557d299d8aa826f7011b1b12`。

## 参考与沿用

主 Agent 规划、专家工具隔离和整合报告的调度思路参考该项目。Agent 运行框架使用 DeepAgents、LangChain 与 LangGraph，不属于本项目自研框架。`frontend/src/components/MarkdownRenderer.tsx` 沿用上游；部分基础工程配置继承后做了精简。

## 本项目的业务实现

当前运行入口为 `korean.server:app` 与 `frontend/src/ResearchApp.tsx`。韩语课程场景、已有 RAG 只读接入、合成销售资料与统计口径、SQL 限制、任务/证据/消息持久化、预算与失败状态、结构化交接、流式对话及验收脚本，均在本项目迭代中实现。开发使用了 Codex 辅助，应按实际承担的设计、修改和验证范围介绍，不应声称全部代码独立手写。

## 对照代码归档

旧 `app/`、教学示例、旧前端、教学数据库配置与原始 `UPSTREAM_README.md` 已从运行目录移至同一工作区：

- `../research/legacy-code-20261117/`：整理前文件，`manifest.json` 记录 76 个文件的 SHA256。
- `../research/upstream-source/deepsearch-agents-8263e95444fd7113557d299d8aa826f7011b1b12/`：固定提交源码。

归档用于查阅和恢复，当前启动不依赖这些路径；单独拷贝本应用时仍可通过上面的固定提交定位来源。

下载到的固定提交根目录未附 LICENSE 文件；保留原始署名和来源。公开发布或分发前需确认上游代码授权，不擅自为上游代码重新声明许可证。

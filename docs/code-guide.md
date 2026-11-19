# 代码结构与请求链路

本文沿一次请求的调用链说明各模块职责、数据边界及失败时的证据保留方式。

## 一次请求经过哪里

1. `frontend/src/ResearchApp.tsx` 发送消息、管理会话并订阅 SSE；`components/Answer.tsx` 展示回答、过程及导出操作。
2. `korean/server.py` 的 `/api/chat` 调用 `conversation.py` 解析课程、竞品、日期与范围。条件缺失时先保存澄清消息，条件齐全再建任务。
3. 服务保存任务，取得并发额度，创建 `budget.py` 的预算和 `tools.py` 的工具容器；离线走固定演示，真实模式进入 `runtime.py`。
4. `runtime.py` 组装一个主 Agent 与 network、course、sales 三个专家；`prompts.py` 定义职责与回答约束。主 Agent 根据请求范围调用专家。
5. `tools.py` 接入搜索、RAG 和销售库，登记证据；`sales.py` 限制只读查询，提供月度和渠道统计，`web_context.py` 处理网页上下文。
6. `handoff.py` 约束专家交接的对象、适用范围与摘录。销售表格取实际工具结果，避免专家重新编写数字。原文匹配仍不等于语义正确。
7. `streaming.py` 提取主 Agent 正文、保存草稿并记录事件；`store.py` 将消息、任务、证据和事件落 SQLite。SSE 先取一致性快照再订阅增量，断线后可重取快照。
8. 完成后服务保存报告和最终状态。导出接口读取已保存的回答，Markdown 直接生成，PDF 使用 `pdf.py`，不重跑模型。

## 关键设计与实现

| 设计问题 | 实现位置 | 约束与限制 |
|---|---|---|
| 为什么需要三个专家 | runtime.py、tools.py | 三类数据与工具的边界；多 Agent 的效果提升尚无严格受控结论 |
| 金额怎么验 | sales.py、scripts/sales_data.py、scripts/evaluate.py | 收款与退款分别按时间统计，用独立 Decimal 参考核对；数据是合成的 |
| 如何防止无限调用 | budget.py、runtime.py | 模型和工具的实际调用均计数，包括重试与委派 |
| 引用是否可靠 | handoff.py、runtime.py、web_context.py | 编号存在、摘录存在和结论被支持是不同问题 |
| 刷新为什么还能看到回答 | streaming.py、store.py、server.py | 事件和草稿先持久化，浏览器重取快照；重启不会自动续跑付费任务 |
| 测试通过代表什么 | tests/、docs/answer-contract-acceptance.md | 工程回归与真实问答语义复核分别报告，保留失败样例 |

本轮回答可靠性修复、预检与证据回放见 [定向回归](reliability-regression.md)。

销售直接呈现链路：`tools.py` 登记实际表格与证据 → `report_tables.py` 保留原值生成带引用Markdown → `runtime.py` 合并模型解释并检查整份预算 → `streaming.py` 转换跨分块标记 → `server.py` 保存及按需导出。相关验证见 `tests/test_report_tables.py`、`tests/test_report_delivery.py` 与真实图测试。效果与限制见 [销售表与新题验收](report-stability.md)。

框架、参考思路及沿用组件见 [来源说明](../UPSTREAM.md)。

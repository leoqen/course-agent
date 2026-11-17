# 代码整理记录（2026-11-17）

本轮围绕运行目录、职责拆分与展示文档整理，不新增业务能力，也未重新执行付费模型问答。历史验收文件与原始结果继续保留；源码移动后哈希变化，旧结果仅对应原冻结版本。

## 整理内容

- 将后端预算、业务工具、提示词与正文流从 runtime 拆至 budget、tools、prompts、streaming，runtime 保留 Agent 组装与报告整合；原导入名称继续兼容已有脚本。
- 将前端 HTTP、类型、状态映射、回答与图标分离，统一排版。保留现有对话、主题、SSE 与导出行为。
- 移除未使用的教学依赖、Ant Design 与 Tailwind，更新 Python 与前端锁文件。requirements.txt 由 uv.lock 导出，requirements-korean.txt 仅作为兼容入口。
- 更新 VS Code 启动、预提交语法检查、忽略规则、业务 README、安装说明、代码讲解与简历材料。参考项目来源和沿用组件继续在 UPSTREAM.md 明确说明。

## 验证

- 锁文件检查与冻结依赖同步通过；Windows 加载中的扩展曾阻止更新，停止无活动任务的服务后完成同步，并清理失效安装元数据。
- `python -m pytest tests -q`：75 passed，1 条既有 anyio / pytest 弃用警告。
- 前端冻结依赖安装、Prettier 格式检查、TypeScript 检查与 Vite 生产构建通过。
- 整理后的服务在本机 8000 端口启动，健康接口、首页及构建资源均返回 200。
- 本轮新增与调整的入口文档本地链接检查通过。

工程回归不能代替真实模型的语义验收。最新新题结果仍为 6 题中 3 pass、3 needs_fix，详见 [回答约束验收](answer-contract-acceptance.md)。

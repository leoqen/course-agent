# 韩语课程 Agent 对话界面

React + TypeScript + Vite，使用普通 CSS。入口为 `src/ResearchApp.tsx`，回答展示在 `src/components/Answer.tsx`，HTTP、类型及状态映射分别放在 `api.ts`、`types.ts` 和 `status.ts`。

```powershell
pnpm install --frozen-lockfile --store-dir .pnpm-store --config.confirmModulesPurge=false --registry=https://registry.npmjs.org
pnpm dev
pnpm build
pnpm format:check
```

默认使用同源 `/api`，开发时 Vite 将请求代理到本机 8000 端口。分开部署可在 `.env.local` 设置 `VITE_API_BASE_URL`；后端需允许对应来源。完整本地安装见 [接入文档](../docs/local-setup.md)。

对话通过 `POST /api/chat` 提交，使用 `/api/conversations` 恢复历史，使用 `/api/tasks/{id}/stream` 的 SSE 快照与增量更新回答。完成后按需调用导出接口获取 Markdown / PDF，主题自动跟随系统。

MarkdownRenderer 沿用上游实现，来源与当前代码边界见 [UPSTREAM.md](../UPSTREAM.md)。

前端固定 pnpm 11.25.0。工作区配置关闭运行命令前的隐式依赖安装，依赖变更后先执行显式冻结安装；Prettier 通过 `pnpm format` 统一格式。

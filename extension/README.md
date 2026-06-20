# Huoke Chrome Extension

浏览器执行层，通过 WebSocket 连接 `local-service`（默认 `ws://127.0.0.1:18766/ws`）。

## 开发

```bash
npm install
npm run dev    # watch 构建到 dist/
```

Chrome → `chrome://extensions` → 开发者模式 → 「加载已解压的扩展程序」→ 选择 `extension/dist`。

## 构建

```bash
npm run build
```

## 目录

- `src/background` — Service Worker，WebSocket 与命令路由
- `src/content` — 页面内执行与平台适配
- `src/injected` — 页面上下文网络 hook
- `src/shared` — 协议与工具
- `src/popup` — 连接状态

详见 [extension-architecture.md](../docs/technical/extension-architecture.md)。

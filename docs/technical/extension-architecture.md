# Huoke 浏览器插件架构方案

## 1. 目标

将「浏览器执行层」从 **Python + Playwright** 迁到 **Chrome Extension + Rust 本地服务**，实现：

- 安装包不再打包 Python / Playwright（体积从 ~300MB 降至 ~30MB 级）
- 消除 Python sidecar 启动链导致的白屏、端口、DLL 问题
- 在真实用户 Chrome 中执行操作，降低 CDP 自动化特征
- 架构清晰、模块独立、便于按平台扩展

**本阶段不删除现有 Python 后端**，新旧架构并行，便于对比与渐进迁移。

---

## 2. 总体架构

```
┌─────────────────────────────────────────────────────────────────┐
│  管理界面 (frontend Vue，逐步改接新 API)                          │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP REST
┌────────────────────────────▼────────────────────────────────────┐
│  local-service/          Rust 本地服务（独立 crate）              │
│  ├── REST API            任务、设置、健康检查                       │
│  ├── WebSocket Hub       与插件双向通信                            │
│  ├── SQLite              任务与采集数据（后续阶段）                  │
│  └── LLM Client          调 DeepSeek（后续阶段）                   │
└────────────────────────────┬────────────────────────────────────┘
                             │ WebSocket  ws://127.0.0.1:18766
┌────────────────────────────▼────────────────────────────────────┐
│  extension/              Chrome MV3 插件（独立目录）                │
│  ├── background          Service Worker：连接、路由、心跳           │
│  ├── content             页面内执行器（按平台注册）                  │
│  ├── injected            页面上下文网络 hook                       │
│  └── popup               连接状态与手动调试                         │
└────────────────────────────┬────────────────────────────────────┘
                             │ DOM / fetch hook
┌────────────────────────────▼────────────────────────────────────┐
│  用户 Chrome  抖音 / 小红书 / 快手                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 端口约定

| 服务 | 端口 | 说明 |
|------|------|------|
| Python 开发后端（旧） | 8000 | `dev-native.sh`，保留 |
| Tauri 桌面版（旧） | 18765 | 保留至迁移完成 |
| Rust local-service（新） | **18766** | 插件专用，避免冲突 |

---

## 3. 目录结构

```
huoke_back/
├── extension/                 # Chrome 插件（独立 npm 工程）
│   ├── manifest.json
│   ├── package.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── background/        # Service Worker
│   │   ├── content/           # Content Scripts
│   │   │   └── platforms/     # 平台适配器（可扩展）
│   │   ├── injected/          # 页面上下文脚本
│   │   ├── shared/            # 协议、常量、工具
│   │   └── popup/             # 插件弹窗 UI
│   └── dist/                  # 构建产物（加载到 Chrome）
│
├── local-service/             # Rust 本地服务（独立 crate）
│   ├── Cargo.toml
│   └── src/
│       ├── main.rs
│       ├── config.rs
│       ├── protocol.rs        # 与 extension/shared 对齐
│       ├── ws/                # WebSocket 连接池
│       ├── api/               # HTTP REST
│       └── commands/          # 命令分发与注册
│
├── frontend/                  # 现有 Vue（后续接 local-service API）
├── backend/                   # 现有 Python（并行保留）
└── docs/technical/
    └── extension-architecture.md
```

---

## 4. 通信协议（Huoke Bridge Protocol v1）

统一 JSON 消息，版本字段便于后续演进。

### 4.1 信封格式

```json
{
  "v": 1,
  "type": "command | result | event | error | ping | pong",
  "id": "uuid",
  "ts": 1710000000000,
  "platform": "douyin | xiaohongshu | kuaishou | null",
  "action": "动作名",
  "payload": {}
}
```

### 4.2 本地服务 → 插件（command）

| action | 说明 | payload 示例 |
|--------|------|----------------|
| `ping` | 心跳探测 | `{}` |
| `get_page_info` | 获取当前页标题/URL | `{}` |
| `network.hook.enable` | 开启 fetch/XHR 嗅探 | `{ "patterns": ["/aweme/"] }` |
| `network.hook.disable` | 关闭嗅探 | `{}` |
| `platform.detect` | 识别当前平台 | `{}` |

### 4.3 插件 → 本地服务（event / result）

| type | action | 说明 |
|------|--------|------|
| `event` | `bridge.connected` | 插件已连接 |
| `event` | `network.captured` | 拦截到 API 响应 |
| `event` | `platform.detected` | 平台识别结果 |
| `result` | `*` | 命令执行结果 |
| `error` | `*` | 命令失败 |

### 4.4 扩展方式

新增平台只需：

1. 在 `extension/src/content/platforms/<platform>/` 实现 `PlatformAdapter`
2. 在 `registry.ts` 注册域名与 adapter
3. 在 `local-service/src/commands/` 增加对应 handler（如需服务端逻辑）

无需改动 background 路由与 WebSocket 层。

---

## 5. 插件内部分层

### 5.1 background（Service Worker）

职责：

- 维护与 `local-service` 的 WebSocket 长连接
- 接收 command，路由到对应 tab 的 content script
- 聚合 content 回传的 event/result
- 断线重连（指数退避）

### 5.2 content（Content Script）

职责：

- 隔离环境内操作 DOM（不直接暴露给页面）
- 调用平台 adapter 执行动作
- 注入 `injected` 脚本到页面上下文

### 5.3 injected（Page Context）

职责：

- hook `fetch` / `XMLHttpRequest` 捕获 JSON
- 通过 `window.postMessage` 与 content script 通信

### 5.4 platforms（平台适配器接口）

```typescript
interface PlatformAdapter {
  readonly id: PlatformId;
  readonly hostPatterns: string[];
  detect(): boolean;
  getPageInfo(): PageInfo;
  handleCommand(action: string, payload: unknown): Promise<unknown>;
}
```

---

## 6. local-service 分层

| 模块 | 职责 |
|------|------|
| `config` | 端口、数据目录、日志 |
| `protocol` | 消息解析、校验、序列化 |
| `ws/hub` | 插件连接管理、广播、请求-响应 |
| `api` | REST：`/health`、`/bridge/status`、`/bridge/command` |
| `commands` | action → handler 注册表 |

后续阶段增加：

- `db/` SQLite 任务与评论存储
- `llm/` DeepSeek 调用
- `jobs/` 任务队列

---

## 7. 迁移路线（分阶段）

### 阶段 0：骨架（当前）

- [x] `extension/` 独立目录与 MV3 骨架
- [x] `local-service/` Rust WebSocket + REST 骨架
- [x] 协议 v1 与 ping / get_page_info / network hook
- [x] 抖音平台 adapter 占位

### 阶段 1：抖音 MVP（2～3 周）

- [x] 抖音搜索页 URL 导航与页面识别
- [x] fetch hook 捕获评论列表 API
- [x] local-service 落库 SQLite
- [x] REST 触发采集任务

### 阶段 2：触达（2～3 周）

- [x] 抖音评论回复 UI 操作（content script）
- [x] 任务队列、配额、重试
- [x] Vue 管理页接 `local-service` API

### 阶段 3：多平台与替换（2～4 周）

- [x] 小红书 adapter
- [x] 快手 adapter
- [x] Tauri 瘦壳仅嵌 Vue + 启动 local-service（去掉 Python sidecar）
- [x] 安装包打包插件 zip + Tauri exe

### 阶段 4：下线 Python 执行层

- [x] 默认路由与导航指向「插件获客」；旧 Playwright 页标注「（旧）」并显示降级横幅
- [x] `npm run setup` / `dev` / `verify` 默认走插件栈；`*:legacy` 保留旧路径
- [x] `setup-extension.sh`、`verify-extension-stack.sh` 替代旧 setup/verify 为推荐入口
- [x] 旧 Playwright 打包脚本标 `[DEPRECATED]`；Tauri 瘦壳移除 Python 后端启动代码
- [ ] Agent 编排迁到 Rust 或保留 Python 仅做 LLM 实验（长期）
- [ ] 完全移除 Playwright 依赖与 legacy bundle 脚本（待存量任务清空后）

---

## 8. 阶段 1 API（抖音采集）

### 8.1 创建任务

```bash
curl -X POST http://127.0.0.1:18766/api/douyin/jobs \
  -H 'Content-Type: application/json' \
  -d '{"keyword":"装修","limit_videos":5,"max_comments_per_video":50}'
```

### 8.2 启动采集

```bash
# 替换 {job_id}；Chrome 需已加载插件，且抖音标签页为当前活动窗口
curl -X POST http://127.0.0.1:18766/api/douyin/jobs/{job_id}/start
```

流程：搜索导航 → 开启 network hook → 等待搜索 API → 逐个打开视频 → 滚动加载评论 → SQLite 落库。

### 8.3 查询结果

| 接口 | 说明 |
|------|------|
| `GET /api/douyin/jobs` | 任务列表 |
| `GET /api/douyin/jobs/:id` | 任务详情（含 video/comment 计数） |
| `GET /api/douyin/jobs/:id/videos` | 采集到的视频 |
| `GET /api/douyin/jobs/:id/comments?limit=200` | 评论列表 |

数据目录：`storage/local-service/huoke_local.db`（可用 `HUOKE_DATA_DIR` 覆盖）。

一键测试：`bash scripts/test-douyin-collect.sh 装修`

### 8.4 同步命令（调试）

```bash
curl -X POST http://127.0.0.1:18766/bridge/command \
  -H 'Content-Type: application/json' \
  -d '{"action":"douyin.search.navigate","payload":{"keyword":"装修"},"wait":true}'
```

---

## 9. 阶段 2 API（评论触达）

### 9.1 配额查询

```bash
curl http://127.0.0.1:18766/api/douyin/quota
```

默认每日回复上限 50，可通过 `HUOKE_DAILY_REPLY_QUOTA` 调整。

### 9.2 单条回复（调试）

```bash
curl -X POST http://127.0.0.1:18766/api/douyin/reply \
  -H 'Content-Type: application/json' \
  -d '{"video_url":"https://www.douyin.com/video/xxx","comment_text":"片段","reply_text":"您好","dry_run":true}'
```

### 9.3 批量触达任务

```bash
curl -X POST http://127.0.0.1:18766/api/douyin/outreach/tasks \
  -H 'Content-Type: application/json' \
  -d '{"source_job_id":"{collect_job_id}","reply_text":"您好","max_items":10}'

curl -X POST http://127.0.0.1:18766/api/douyin/outreach/tasks/{task_id}/start
curl -X POST http://127.0.0.1:18766/api/douyin/outreach/tasks/{task_id}/pause
```

Vue 管理页：侧边栏 **插件获客** → `/extension-bridge`

一键测试：`bash scripts/test-douyin-outreach.sh {collect_job_id} "回复文案"`

---

## 10. 开发与打包

### 10.0 根目录快捷命令（推荐）

| 命令 | 说明 |
|------|------|
| `npm run setup` | `setup-extension.sh --install` |
| `npm run dev` | `dev-extension.sh` |
| `npm run verify` | `verify-extension-stack.sh` |
| `npm run setup:legacy` | 旧 Playwright 栈安装 |
| `npm run dev:legacy` | 旧 `dev.sh` |
| `npm run verify:legacy` | 旧 `verify-huoke-standalone.sh` |

### 10.1 本地开发

```bash
# 终端 1：Rust 本地服务
cd local-service && cargo run

# 终端 2：插件开发构建
cd extension && npm install && npm run dev

# Chrome → chrome://extensions → 开发者模式 → 加载 extension/dist
```

或使用根目录：

```bash
bash scripts/dev-extension.sh
```

### 10.2 生产打包（瘦壳，默认）

```bash
# 组装 bundle：前端 + local-service + extension.zip
bash scripts/prepare_desktop_thin_bundle.sh

# 打 Tauri 安装包
cd desktop && npm run tauri build
```

`desktop/bundle/` 内容：

| 文件 | 说明 |
|------|------|
| `runtime/huoke-local-service` | Rust 本地桥接（18766） |
| `frontend-dist/` | Vue 静态资源（18765） |
| `huoke-extension.zip` | Chrome 插件，需手动加载 |

瘦壳启动后默认打开 `/extension-bridge`。旧 Python bundle 仍可通过 `HUOKE_DESKTOP_LEGACY=1` 使用 `prepare_desktop_bundle.sh`。

### 10.3 Tauri 瘦壳开发

```bash
cd desktop && npm run tauri dev
# 自动执行 scripts/desktop-dev-thin.sh
```

---

## 11. 阶段 3（多平台 + 瘦壳）

### 11.1 平台 adapter

| 平台 | 搜索导航 | 内容导航 | 评论滚动 |
|------|----------|----------|----------|
| 抖音 | `douyin.search.navigate` | `douyin.video.navigate` | `douyin.comments.scroll` |
| 小红书 | `xhs.search.navigate` | `xhs.note.navigate` | `xhs.comments.scroll` |
| 快手 | `kuaishou.search.navigate` | `kuaishou.video.navigate` | `kuaishou.comments.scroll` |

### 11.2 安装 Chrome 插件

1. 解压 `desktop/bundle/huoke-extension.zip` 或加载 `extension/dist`
2. 打开对应平台页面并保持为活动标签
3. popup 显示「已连接」后即可采集/触达

### 11.3 验收

- [ ] 三平台 `get_page_info` 返回正确 platform
- [ ] `prepare_desktop_thin_bundle.sh` 成功
- [ ] Tauri 启动后打开 `/extension-bridge` 无白屏
- [ ] `huoke-extension.zip` 可加载到 Chrome

---

## 12. 稳定性设计

| 机制 | 说明 |
|------|------|
| 断线重连 | background 指数退避重连 WebSocket |
| 命令超时 | local-service 对 command 设 30s 超时 |
| 心跳 | ping/pong 每 15s |
| 端口隔离 | 18766 专用于插件架构 |
| 平台隔离 | 各平台 adapter 独立，互不影响 |
| 协议版本 | 消息带 `v` 字段，便于灰度升级 |
| 错误显式化 | 统一 `error` 类型，避免静默失败 |

---

## 13. 与现有 Python 的关系

| 能力 | 阶段 0～2 | 阶段 3+ |
|------|-----------|---------|
| 浏览器执行 | Python Playwright + **插件并行** | 以插件为主 |
| 任务 API | Python FastAPI | local-service REST |
| 管理 UI | Vue → Python API | Vue → local-service |
| 桌面安装包 | 旧 Python bundle | 新瘦包 |

**原则**：新功能在 `extension/` + `local-service/` 开发；Python 仅维护存量，不新增 Playwright 能力。

---

## 14. 风险与对策

| 风险 | 对策 |
|------|------|
| MV3 Service Worker 休眠 | 心跳 + 事件驱动唤醒；重连 |
| 平台检测插件注入 | injected 脚本尽量轻量；hook 最小化 |
| 用户未装插件 | popup 与 Tauri 启动时检测连接状态 |
| 接口风控 | 降频、随机延迟、账号预热（迁自 antibot 策略） |
| 开发双栈维护 | 明确阶段边界，按平台逐个迁移 |

---

## 15. 验收标准

### 阶段 0

- [ ] `cargo run` 启动 local-service，`GET /health` 返回 ok
- [ ] Chrome 加载 `extension/dist`，popup 显示「已连接」
- [ ] 打开抖音页，执行 `get_page_info` 返回 URL/title
- [ ] 开启 `network.hook.enable` 后，控制台可见 `network.captured` 事件
- [ ] 插件与 local-service 代码均在独立目录，无 Python 依赖

### 阶段 1

- [ ] `POST /api/douyin/jobs` 创建任务成功
- [ ] `POST /api/douyin/jobs/:id/start` 后任务状态变为 `completed`
- [ ] `GET .../videos` 返回搜索到的视频
- [ ] `GET .../comments` 返回评论数据
- [ ] SQLite 文件 `storage/local-service/huoke_local.db` 有记录

### 阶段 2

- [ ] `douyin.comment.reply` 在视频页找到目标评论并发送
- [ ] `POST /api/douyin/outreach/tasks` 从采集任务生成触达队列
- [ ] 触达任务遵守每日配额，失败自动重试
- [ ] Vue `/extension-bridge` 页面可管理采集与触达

# 抖音热点监控分析平台

基于 `Python 3.12 + FastAPI + SQLAlchemy + Playwright + SQLite + Vue3 + Element Plus` 的热点监控系统，支持抖音热榜抓取、趋势分析、AI 日报生成、PDF 导出。本地开发与桌面版均使用 **系统 Chrome + SQLite**，无需 Docker。

## 功能覆盖

1. Playwright 自动登录抖音网页版（扫码登录）
2. Cookie 持久化（`storage/douyin/storage_state.json`）
3. 每日定时抓取热榜前 100
4. 保存标题、作者、点赞、评论、分享、发布时间
5. 记录每日排名变化
6. REST API
7. Vue 后台管理系统
8. 热门视频排行
9. 热门作者排行
10. 趋势图（ECharts）
11. 对接 OpenAI / DeepSeek
12. 自动热点日报
13. PDF 导出
14. 完整 README
15. 数据库初始化 SQL
16. Repository 模式
17. Alembic 迁移
18. 单元测试
19. `.env` 配置

## Skill 统一架构（2026-06）

业务能力统一通过 **Skill** 暴露，REST / Agent / Pipeline 共用 `SkillRunnerService`：

| 入口 | 说明 |
|------|------|
| `POST /api/agent/skills/execute` | 直接执行任意 Skill |
| `POST /api/platforms/{platform}/...` | 平台 REST（内部适配为 Skill） |
| `POST /api/agent/pipeline/keyword-video-comments` | 对外 Pipeline（`pipeline-keyword-video-comments`） |
| Agent 对话 `/skill-id` | invoke_skill 与上述同源 |

核心 Skill：`douyin-keyword-comments`、`xhs-keyword-comments`、`follow-user`、`send-dm`、`pipeline-keyword-video-comments`。  
Skill 定义：`backend/storage/skills/global.json`。

## 目录结构

```text
.
├── backend
│   ├── app
│   ├── alembic
│   ├── sql/init.sql
│   └── tests
├── frontend
├── desktop          # Tauri 原生桌面应用
└── scripts
```

## 本地开发（Mac，系统 Chrome）

### 1) 配置

```bash
cp .env.local.example .env.local
# 编辑 .env.local，填入 DEEPSEEK_API_KEY 等密钥
```

关键项：

| 变量 | 说明 |
|------|------|
| `ANTIBOT_BROWSER_CHANNEL=chrome` | 使用本机 Google Chrome（必须预装） |
| `AGENT_HEADLESS=false` | Agent 可见浏览器窗口 |

需已安装 [Google Chrome](https://www.google.com/chrome/)。数据库由 `dev-native.sh` 自动使用 SQLite（`storage/dev/huoke.db`）。

### 2) 一键启动

```bash
# 后端 + 前端
bash scripts/dev.sh
# 或
npm run dev

# 仅后端（SQLite + 热更新）
bash scripts/dev-native.sh
# 或
npm run dev:backend
```

另开终端启动前端（若未用 dev.sh）：

```bash
cd frontend && npm install && npm run dev
```

前端地址：`http://localhost:5173`  
后端地址：`http://localhost:8000`  
API 文档：`http://localhost:8000/docs`

### 3) 验证

```bash
npm run verify
# 或
bash scripts/verify-huoke-standalone.sh
```

## 抖音登录与抓取

1. 将 `.env` 中 `DOUYIN_HEADLESS=false`
2. 调用 `POST /api/douyin/login`，浏览器打开后扫码登录
3. 登录成功后会保存 Cookie
4. 再把 `DOUYIN_HEADLESS=true`，调用 `POST /api/crawl/hot`

## 关键 API

- `GET /api/health`
- `POST /api/douyin/login`
- `POST /api/crawl/hot?limit=100`
- `GET /api/hot/videos`
- `GET /api/hot/authors`
- `GET /api/videos/{video_id}/trend?days=30`
- `GET /api/overview`
- `POST /api/reports/daily?provider=template|openai|deepseek`
- `GET /api/reports`
- `GET /api/reports/{report_date}/pdf`

## AI 日报

在 `.env` 填入：

- `OPENAI_API_KEY`
- `DEEPSEEK_API_KEY`

即可通过 `provider` 切换模型。

## 测试

```bash
cd backend
pytest

# 任务创建 → 编排 → 执行 全流程
npm run test:task-flow
# 或
bash scripts/test_task_flow.sh

# 仅编排后计划执行模拟（dry-run，不调用浏览器）
cd backend && pytest tests/test_task_planned_execution_simulation.py -v
```

编排任务相关：

```bash
bash scripts/test_orchestration.sh
```

## 原生桌面应用（macOS / Windows）

使用 **Tauri 2** 将前后端打包为可安装的原生应用（macOS `.app` / `.dmg`，Windows NSIS `.exe`），启动后自动拉起 Python 后端（SQLite），在原生窗口中打开管理界面。

### 客户安装包（完整包）

安装包内已自带，**客户电脑无需**预装 Node / Python / Rust：

| 内置 | 说明 |
|------|------|
| Tauri 桌面壳 | 原生窗口（Windows 安装包会引导安装 WebView2） |
| 前端静态资源 | Vue 构建产物 |
| Python 3.12 运行时 | 可移植完整 Python + 全部后端依赖 |
| FastAPI 后端 + SQLite | 数据与任务本地存储 |
| MSVC 运行库 DLL | `vcruntime140*.dll` 已打入 bundle，一般无需单独安装 VC++ |
| 离线修复包 | `runtime/repair-wheels` 供首次启动异常时离线修复原生扩展 |

客户必须额外安装：

| 依赖 | 说明 |
|------|------|
| **Google Chrome** | 浏览器自动化依赖本机 Chrome；未安装时应用后端无法启动 |

> 不再内置 Playwright Chromium，安装包体积更小，但 Chrome 为硬性前置条件。

构建机仍需 Node.js 20+、Rust/Cargo、Google Chrome（用于打包时冒烟验证）；Python 在打包时自动下载进安装包。

### 开发机构建依赖

| 依赖 | 说明 |
|------|------|
| Google Chrome | 打包验证与本地调试浏览器自动化 |
| Node.js 20+ | 构建前端 |
| Rust / Cargo | 构建 Tauri 壳 |

### macOS 一键打包

```bash
npm run build:mac
# 或
./scripts/build_native_mac.sh
```

`npm run build` 前会自动执行 `scripts/prepare_desktop_bundle.sh`（构建前端 + 打入 Python bundle）。

产物：

- `desktop/src-tauri/target/release/bundle/macos/Huoke.app`
- `desktop/src-tauri/target/release/bundle/dmg/Huoke_0.1.0_aarch64.dmg`

### Windows 一键打包

```powershell
pwsh ./scripts/build_native_win.ps1
```

打包前会自动执行 `scripts/prepare_desktop_bundle.ps1`。CI 还会跑：

- `scripts/validate_desktop_scripts.ps1`（脚本语法 + 本地 bundle 启动冒烟）
- `scripts/verify_windows_bundle.ps1`（Python 依赖、manifest、Chrome 通道）
- `scripts/verify_nsis_installed.ps1`（静默安装 NSIS 包后启动冒烟）

产物：

- `desktop/src-tauri/target/release/bundle/nsis/*.exe`

用户数据目录：

- macOS：`~/Library/Application Support/com.huoke.desktop/`
- Windows：`%APPDATA%\com.huoke.desktop\`

### 开发调试（桌面模式）

```bash
# 终端 1：启动后端（desktop 模式托管前端静态文件）
./scripts/desktop-dev.sh

# 终端 2：Tauri 开发窗口
cd desktop && npm install && npm run dev
```

首次运行会在 `~/Library/Application Support/com.huoke.desktop/.env.desktop` 生成配置，按需填入 `DEEPSEEK_API_KEY` 等密钥后重启应用。

### 架构说明

1. 前端以 `VITE_API_BASE_URL=/api` 构建，由 FastAPI 同源托管（`DESKTOP_MODE=true`）
2. Python 后端 + 可移植运行时打入 `desktop/bundle/`，随安装包 Resources 分发
3. 用户数据（SQLite、storage、Chrome profile）保存在各平台应用数据目录（见上）

## 注意事项

1. 抖音页面结构可能变动，`backend/app/services/douyin_crawler.py` 中选择器可按需调整。
2. 生产部署请自行配置 API Key、跨域域名与持久化存储路径。
3. 如果服务器无图形环境，首次扫码可在开发机生成 Cookie 再同步 `storage_state.json`。

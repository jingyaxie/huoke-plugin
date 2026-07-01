# Huoke 获客平台

Chrome 插件 + Rust 本地服务 + Vue 管理界面 + Tauri 桌面瘦壳。浏览器操作在**用户 Chrome** 中执行，无需打包 Python / Playwright。

## 架构

```text
Vue 管理页 → local-service :18766 → WebSocket → Chrome 插件 → 抖音页面
```

| 组件 | 目录 | 说明 |
|------|------|------|
| Chrome 插件 | `extension/` | DOM 自动化、网络 hook |
| 本地服务 | `local-service/` | 任务 API、SQLite、编排 |
| 管理界面 | `frontend/` | Vue3 + Element Plus |
| 桌面壳 | `desktop/` | Tauri，托管静态页 + 拉起 local-service |

## 快速开始

### 1. 配置（可选）

```bash
cp .env.local.example .env.local
# 按需填写 DEEPSEEK_API_KEY、HUOKE_BRIDGE_SECRET 等
```

### 2. 初始化

```bash
npm run setup
```

构建 `extension/dist`、`local-service`、安装前端依赖。

### 3. 开发

```bash
# 终端 1：local-service + 构建插件
npm run dev

# 终端 2：管理页
cd frontend && npm run dev
# → http://localhost:5173/extension-bridge
```

Chrome：`chrome://extensions` → 加载 `extension/dist` → 打开抖音并登录。

### 4. 验证

```bash
npm run verify
bash scripts/preflight-douyin-extension.sh   # 需抖音页在前台
bash scripts/test-douyin-collect.sh 装修      # 采集冒烟
```

## npm 脚本

| 命令 | 说明 |
|------|------|
| `npm run setup` | 安装依赖并构建插件 + local-service |
| `npm run dev` | 启动 local-service，重建插件 |
| `npm run verify` | 检查 health / API / 插件连接 |
| `npm run bundle` | 组装 `desktop/bundle`（前端 + local-service + 插件 zip） |
| `npm run build:extension` | 仅构建 Chrome 插件，发布到 `dist/releases/` |
| `npm run build:mac` | macOS `.app` / `.dmg` |
| `npm run build:win` | Windows NSIS 安装包 |
| `npm run test:collect` | 关键词采集 API 冒烟 |
| `npm run test:extension` | 插件分步测试（慢，需抖音前台） |

## 脚本目录

```text
scripts/
├── setup.sh              # 环境初始化
├── dev.sh                # 本地开发
├── verify.sh             # 健康检查
├── prepare-bundle.sh     # 桌面打包资源（macOS/Linux）
├── prepare-bundle.ps1    # 桌面打包资源（Windows）
├── desktop-dev.sh        # Tauri dev 前置服务
├── build-desktop-mac.sh
├── build-desktop-win.ps1
├── test-douyin-*.sh      # 抖音插件联调测试
└── lib/common.sh         # 公共函数
```

## 桌面应用打包（Windows / macOS）

安装包内含：**Tauri 壳 + Vue 管理页 + Rust local-service + Chrome 插件**，无需 Python。

| 内置 | 说明 |
|------|------|
| 桌面应用 | 打开即用，自动启动 local-service |
| Chrome 插件 | 首次启动自动解压，并尝试拉起 Chrome 加载 |
| WebView2 | Windows 轻量包会在线安装；离线完整包内置 WebView2 安装器 |

客户仍需安装 **Google Chrome**（未内置浏览器）。首次启动会打开专用 Chrome 窗口，**登录抖音一次**即可。

### 版本化发布目录

在 **Windows / macOS 构建机**上执行 `npm run build:win` 或 `npm run build:mac` 后，`dist/releases/` **只保留**：

| 文件 | 说明 |
|------|------|
| `huoke-desktop-v{版本}-windows-setup.exe` | Windows 轻量安装包（含 local-service + 插件，安装 WebView2 时需要联网） |
| `huoke-desktop-v{版本}-windows-offline-setup.exe` | Windows 离线完整安装包（含 local-service + 插件 + WebView2 离线安装器） |
| `huoke-desktop-v{版本}-macos.dmg` | macOS 安装包（含 local-service + 插件） |
| `huoke-extension-v{版本}.zip` | Chrome 插件（手动更新用） |
| `index.html` / `RELEASES.json` | 下载页与清单 |

Windows 完整打包会出现 **轻量安装包 + 离线完整安装包 + 1 个插件 zip**；macOS 完整打包会出现 **1 个 DMG + 1 个插件 zip**。脚本会自动清理旧的 standalone local-service 等多余文件。

`npm run bundle` 仅组装 `desktop/bundle/`，不写入 `dist/releases/`。

仅发插件：`npm run build:extension`

### Windows 完整安装包

在 **Windows 构建机**上执行：

```powershell
npm run build:win
```

产物：`dist/releases/huoke-desktop-v*-windows-setup.exe`（Tauri 原始产物仍在 `desktop/src-tauri/target/release/bundle/nsis/`）
同时会产出：`dist/releases/huoke-desktop-v*-windows-offline-setup.exe`

只打其中一种 Windows 包：

```powershell
npm run build:win:light
npm run build:win:offline
```

用户流程：

1. 双击安装 `.exe`（无需管理员，安装到 `%LOCALAPPDATA%\com.huoke.desktop`）
2. 从开始菜单或桌面快捷方式打开「AI获客平台」
3. 应用自动启动本地服务；若插件未连接，点击 **「启动浏览器插件」**
4. 在打开的 Chrome 窗口登录抖音，即可创建采集任务

### macOS

```bash
npm run build:mac
```

产物：`dist/releases/huoke-desktop-v*-macos.dmg`（Tauri 原始产物仍在 `desktop/src-tauri/target/release/bundle/macos/`）

### Windows

```powershell
npm run build:win
```

产物：`dist/releases/huoke-desktop-v*-windows-setup.exe`（Tauri 原始产物仍在 `desktop/src-tauri/target/release/bundle/nsis/`）
同时会产出：`dist/releases/huoke-desktop-v*-windows-offline-setup.exe`

### Tauri 开发

```bash
npm run bundle          # 首次需组装 bundle
cd desktop && npm run dev
```

## 端口

| 服务 | 端口 |
|------|------|
| local-service | 18766 |
| 桌面静态 UI | 18765 |
| 前端 dev server | 5173 |

## 数据

- 插件任务 SQLite：`storage/local-service/huoke_local.db`（可用 `HUOKE_DATA_DIR` 覆盖）
- 桌面用户数据：macOS `~/Library/Application Support/com.huoke.desktop/`

## 文档

- 插件架构详解：`docs/technical/extension-architecture.md`

## 说明

仓库中 `backend/` 为历史 Python 栈，**默认工作流不再使用**。新功能在 `extension/` + `local-service/` 开发。

# Huoke Local Service

Rust 本地桥接服务，供 Chrome 插件通过 WebSocket 连接。

## 运行

```bash
cargo run
# 或指定端口
HUOKE_LOCAL_PORT=18766 cargo run
```

## HTTP API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/bridge/status` | 插件连接数 |
| POST | `/bridge/ping` | 向插件广播 ping |
| POST | `/bridge/command` | 向插件下发命令 |

### 下发命令示例

```bash
curl -X POST http://127.0.0.1:18766/bridge/command \
  -H 'Content-Type: application/json' \
  -d '{"action":"get_page_info","payload":{}}'
```

## WebSocket

`ws://127.0.0.1:18766/ws`

协议见 [extension-architecture.md](../docs/technical/extension-architecture.md)。

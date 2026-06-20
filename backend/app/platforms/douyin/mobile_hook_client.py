"""抖音 On-Device Hook Bridge HTTP 客户端（Frida/LSPosed，非 MITM）。"""
from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BRIDGE_TOKEN_HEADER = "X-AiSales-Bridge-Token"
DEFAULT_BRIDGE_TOKEN = "dyb_76f3c4d915a7465d94c0a61a8d8d67e2"
DEFAULT_PORT = 59528


def resolve_bridge_token(explicit: str | None = None) -> str:
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    return (
        os.environ.get("DOUYIN_BRIDGE_TOKEN")
        or os.environ.get("DOUYIN_TOKEN")
        or DEFAULT_BRIDGE_TOKEN
    )


@dataclass(frozen=True)
class BridgeProbeResult:
    ok: bool
    ready: bool
    host: str
    port: int
    error: str | None = None
    payload: dict[str, Any] | None = None


class DouyinMobileHookClient:
    """通过 adb forward 或 WiFi IP 访问手机内 127.0.0.1:59528 Bridge。"""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = DEFAULT_PORT,
        timeout: float = 8.0,
        token: str | None = None,
        adb_serial: str | None = None,
        auto_forward: bool = True,
    ) -> None:
        self.host = host.strip() or "127.0.0.1"
        self.port = int(port)
        self.timeout = float(timeout)
        self.token = resolve_bridge_token(token)
        self.adb_serial = (adb_serial or os.environ.get("DOUYIN_HOOK_ADB_SERIAL") or "").strip() or None
        self.auto_forward = auto_forward
        self.base_url = f"http://{self.host}:{self.port}"

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            BRIDGE_TOKEN_HEADER: self.token,
        }

    def ensure_adb_forward(self) -> tuple[bool, str | None]:
        """USB 调试时把本机端口转发到手机 Bridge。"""
        if self.host not in {"127.0.0.1", "localhost"}:
            return True, None
        cmd = ["adb"]
        if self.adb_serial:
            cmd.extend(["-s", self.adb_serial])
        cmd.extend(["forward", f"tcp:{self.port}", f"tcp:{self.port}"])
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
        except FileNotFoundError:
            return False, "adb 未安装或不在 PATH"
        except subprocess.TimeoutExpired:
            return False, "adb forward 超时"
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip() or f"adb forward exit {proc.returncode}"
            return False, err
        return True, None

    async def request(
        self,
        method: str,
        endpoint: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.request(
                    method=method.upper(),
                    url=url,
                    headers=self._headers(),
                    json=json_body,
                    params=params,
                )
            try:
                payload = resp.json()
            except ValueError:
                payload = {"success": resp.is_success, "text": resp.text}
            if isinstance(payload, dict):
                payload.setdefault("_http_status", resp.status_code)
                if resp.status_code >= 400:
                    payload.setdefault("success", False)
                return payload
            return {"success": resp.is_success, "data": payload, "_http_status": resp.status_code}
        except httpx.ConnectError as exc:
            return {"success": False, "error": f"ConnectionError: {exc}"}
        except httpx.TimeoutException as exc:
            return {"success": False, "error": f"Timeout: {exc}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def health(self) -> dict[str, Any]:
        return await self.request("GET", "/health")

    async def search(self, keyword: str, *, count: int = 10, offset: int = 0) -> dict[str, Any]:
        return await self.request(
            "POST",
            "/search",
            json_body={
                "keyword": keyword,
                "count": str(count),
                "offset": str(offset),
            },
        )

    async def probe(self) -> BridgeProbeResult:
        if self.auto_forward and self.host in {"127.0.0.1", "localhost"}:
            ok, err = self.ensure_adb_forward()
            if not ok:
                return BridgeProbeResult(
                    ok=False,
                    ready=False,
                    host=self.host,
                    port=self.port,
                    error=err or "adb forward failed",
                )
        payload = await self.health()
        adapter = payload.get("adapter") if isinstance(payload.get("adapter"), dict) else {}
        ready = bool(
            payload.get("success")
            or payload.get("status") == "ok"
            or adapter.get("ready")
        )
        error = None if ready else str(payload.get("error") or "bridge_not_ready")
        return BridgeProbeResult(
            ok=ready,
            ready=ready,
            host=self.host,
            port=self.port,
            error=error,
            payload=payload if isinstance(payload, dict) else None,
        )

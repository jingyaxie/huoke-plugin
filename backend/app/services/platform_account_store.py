from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from app.core.config import Settings
from app.platforms.account_id import normalize_account_id
from app.platforms.constants import BINDABLE_PLATFORMS, PLATFORM_LABELS
from app.platforms.registry import get_hot_crawler, get_session_store
from app.platforms.tenant import normalize_tenant_id
from app.schemas.platform_account import PlatformAccountCreate, PlatformAccountOut, PlatformBindingStatus


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_platform_cookie_ready(status: dict) -> bool:
    if status.get("cookie_ok") is True:
        return True
    state = str(status.get("status") or "").strip().lower()
    if state in {"ready", "authenticated"}:
        return True
    if status.get("profile_ready") and state == "incomplete":
        return True
    auth_status = str(status.get("auth_status") or "").strip().lower()
    return auth_status == "authenticated" and status.get("needs_relogin") is False


def _profile_restore_ready(status: dict) -> bool:
    """桌面端 Profile 已有数据、可尝试无 JSON 恢复（打开浏览器后自动登录）。"""
    return bool(status.get("profile_ready")) and str(status.get("status") or "").lower() == "incomplete"


def _profile_fields_from_login_status(login_status: dict) -> dict[str, str | None]:
    platform_user_id = str(
        login_status.get("platform_user_id")
        or login_status.get("uid")
        or ""
    ).strip()
    legacy_account_id = str(login_status.get("account_id") or "").strip()
    if not platform_user_id and legacy_account_id and not legacy_account_id.startswith("huoke:"):
        platform_user_id = legacy_account_id

    nickname = str(
        login_status.get("nickname")
        or login_status.get("display_name")
        or login_status.get("username")
        or ""
    ).strip() or None
    avatar_url = login_status.get("avatar_url")
    avatar = str(avatar_url).strip() if isinstance(avatar_url, str) and avatar_url.strip() else None
    return {
        "platform_user_id": platform_user_id or None,
        "nickname": nickname,
        "avatar_url": avatar,
    }


class PlatformAccountStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _index_path(self, tenant_id: str):
        safe = normalize_tenant_id(tenant_id)
        path = self.settings.storage_root / "tenants" / safe / "accounts" / "index.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _load_index(self, tenant_id: str) -> dict:
        path = self._index_path(tenant_id)
        if not path.exists():
            return {"items": [], "active_account_id": "default"}
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {"items": [], "active_account_id": "default"}
        raw.setdefault("items", [])
        raw.setdefault("active_account_id", "default")
        return raw

    def _save_index(self, tenant_id: str, payload: dict) -> None:
        path = self._index_path(tenant_id)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _ensure_default(self, tenant_id: str) -> dict:
        raw = self._load_index(tenant_id)
        items = list(raw.get("items") or [])
        if not any(item.get("id") == "default" for item in items):
            now = _utc_now().isoformat()
            items.insert(
                0,
                {"id": "default", "label": "默认账号", "created_at": now, "updated_at": now},
            )
            raw["items"] = items
            raw["active_account_id"] = raw.get("active_account_id") or "default"
            self._save_index(tenant_id, raw)
        return raw

    def list_accounts(self, tenant_id: str) -> list[PlatformAccountOut]:
        raw = self._ensure_default(tenant_id)
        return [PlatformAccountOut.model_validate(item) for item in raw.get("items", [])]

    def get_active_account_id(self, tenant_id: str) -> str:
        raw = self._ensure_default(tenant_id)
        return normalize_account_id(raw.get("active_account_id"))

    def set_active_account(self, tenant_id: str, account_id: str) -> str:
        account_id = normalize_account_id(account_id)
        raw = self._ensure_default(tenant_id)
        ids = {item.get("id") for item in raw.get("items", [])}
        if account_id not in ids:
            raise KeyError(account_id)
        raw["active_account_id"] = account_id
        self._save_index(tenant_id, raw)
        return account_id

    def create_account(self, tenant_id: str, payload: PlatformAccountCreate) -> PlatformAccountOut:
        raw = self._ensure_default(tenant_id)
        account_id = normalize_account_id(payload.id)
        items = list(raw.get("items") or [])
        if any(item.get("id") == account_id for item in items):
            raise ValueError(f"账号 ID 已存在: {account_id}")
        now = _utc_now().isoformat()
        record = {
            "id": account_id,
            "label": payload.label.strip(),
            "created_at": now,
            "updated_at": now,
        }
        items.append(record)
        raw["items"] = items
        self._save_index(tenant_id, raw)
        return PlatformAccountOut.model_validate(record)

    def delete_account(self, tenant_id: str, account_id: str) -> bool:
        account_id = normalize_account_id(account_id)
        if account_id == "default":
            raise ValueError("不能删除默认账号")
        raw = self._ensure_default(tenant_id)
        items = list(raw.get("items") or [])
        new_items = [item for item in items if item.get("id") != account_id]
        if len(new_items) == len(items):
            return False
        raw["items"] = new_items
        if raw.get("active_account_id") == account_id:
            raw["active_account_id"] = "default"
        self._save_index(tenant_id, raw)
        return True

    def get_account(self, tenant_id: str, account_id: str) -> PlatformAccountOut | None:
        account_id = normalize_account_id(account_id)
        for item in self.list_accounts(tenant_id):
            if item.id == account_id:
                return item
        return None

    def update_account_label(self, tenant_id: str, account_id: str, label: str) -> PlatformAccountOut:
        account_id = normalize_account_id(account_id)
        cleaned = label.strip()
        if not cleaned:
            raise ValueError("账号名称不能为空")
        raw = self._ensure_default(tenant_id)
        items = list(raw.get("items") or [])
        updated: dict | None = None
        now = _utc_now().isoformat()
        for item in items:
            if item.get("id") != account_id:
                continue
            item["label"] = cleaned
            item["updated_at"] = now
            updated = item
            break
        if updated is None:
            raise KeyError(account_id)
        raw["items"] = items
        self._save_index(tenant_id, raw)
        return PlatformAccountOut.model_validate(updated)

    def confirm_platform_binding(
        self,
        tenant_id: str,
        account_id: str,
        platform: str,
        *,
        label: str | None = None,
    ) -> dict:
        platform = platform.strip().lower()
        if platform not in BINDABLE_PLATFORMS:
            raise ValueError(f"不支持绑定的平台: {platform}")
        account_id = normalize_account_id(account_id)
        account = self.get_account(tenant_id, account_id)
        if account is None:
            raise KeyError(account_id)

        if label and label.strip():
            account = self.update_account_label(tenant_id, account_id, label.strip())

        session_store = get_session_store(self.settings, platform)
        login_status = session_store.login_status(tenant_id, account_id)
        cookie_ready = _is_platform_cookie_ready(login_status)

        profile = _profile_fields_from_login_status(login_status)
        display_name = account.label
        return {
            "ok": cookie_ready,
            "tenant_id": tenant_id,
            "account_id": account_id,
            "platform": platform,
            "label": account.label,
            "display_name": display_name,
            "platform_user_id": profile["platform_user_id"],
            "nickname": profile["nickname"],
            "avatar_url": profile["avatar_url"],
            "cookie_ready": cookie_ready,
            "login_status": login_status,
        }

    def platform_bindings(self, tenant_id: str, account_id: str) -> list[PlatformBindingStatus]:
        account_id = normalize_account_id(account_id)
        bindings: list[PlatformBindingStatus] = []
        for platform in sorted(BINDABLE_PLATFORMS):
            store = get_session_store(self.settings, platform)
            status = store.login_status(tenant_id, account_id)
            profile = _profile_fields_from_login_status(status)
            bindings.append(
                PlatformBindingStatus(
                    platform=platform,
                    platform_label=PLATFORM_LABELS.get(platform, platform),
                    status=status.get("status", "missing"),
                    message=str(status.get("message") or ""),
                    cookie_count=int(status.get("cookie_count") or 0),
                    cookie_ready=_is_platform_cookie_ready(status),
                    platform_user_id=profile["platform_user_id"],
                    nickname=profile["nickname"],
                    avatar_url=profile["avatar_url"],
                )
            )
        return bindings

    async def start_server_login(
        self,
        tenant_id: str,
        platform: str,
        account_id: str,
        *,
        restore: bool = False,
    ) -> dict:
        from app.platforms.douyin.crawler import DouyinCrawler
        from app.platforms.interactive_login import (
            restart_interactive_login_for_platform,
            stop_interactive_session,
        )
        from app.platforms.xiaohongshu.crawler import XhsCrawler

        _interactive_crawler_cls = {
            "douyin": DouyinCrawler,
            "xiaohongshu": XhsCrawler,
        }

        platform = platform.strip().lower()
        if platform not in BINDABLE_PLATFORMS:
            raise ValueError(f"不支持绑定的平台: {platform}")
        account_id = normalize_account_id(account_id)
        if self.get_account(tenant_id, account_id) is None:
            raise KeyError(account_id)

        session_store = get_session_store(self.settings, platform)
        login_status = session_store.login_status(tenant_id, account_id)
        cookie_ready = _is_platform_cookie_ready(login_status)
        profile_restore = _profile_restore_ready(login_status)
        crawler_cls = _interactive_crawler_cls.get(platform)

        if crawler_cls is not None and not restore:
            alive = crawler_cls.get_interactive_session(platform, tenant_id, account_id)
            if alive and crawler_cls._session_page_alive(alive):
                return {
                    "status": "running",
                    "message": "浏览器窗口已在运行",
                    "tenant_id": tenant_id,
                    "account_id": account_id,
                    "platform": platform,
                    "storage_state_path": str(session_store.path_for(tenant_id, account_id)),
                }

        stopped: list[str] = []
        if not restore:
            stopped = await restart_interactive_login_for_platform(tenant_id, account_id, platform)
        elif await stop_interactive_session(platform, tenant_id, account_id):
            stopped.append(platform)

        crawler = get_hot_crawler(self.settings, platform, tenant_id, account_id=account_id)
        result = await crawler.start_interactive_login_session(restore=restore)
        if stopped:
            labels = ", ".join(stopped)
            result = {
                **result,
                "stopped_platforms": stopped,
                "message": f"已关闭 {labels} 的旧窗口；{result.get('message', '')}".strip(),
            }
        elif restore and (cookie_ready or profile_restore):
            result = {
                **result,
                "message": "已用本机 Cookie 打开窗口",
            }
        elif restore and not cookie_ready and not profile_restore:
            result = {
                **result,
                "message": "未找到可用登录态，正在打开 Chrome 登录窗口",
            }

        if crawler_cls is not None and str(result.get("status") or "").lower() != "running":
            sess = crawler_cls.get_interactive_session(platform, tenant_id, account_id)
            if sess and crawler_cls._session_page_alive(sess):
                result = {**result, "browser_ready": True}

        return {
            **result,
            "storage_state_path": str(session_store.path_for(tenant_id, account_id)),
        }

    def upload_storage_state(
        self, tenant_id: str, platform: str, account_id: str, storage_state: dict
    ) -> dict:
        platform = platform.strip().lower()
        if platform not in BINDABLE_PLATFORMS:
            raise ValueError(f"不支持绑定的平台: {platform}")
        account_id = normalize_account_id(account_id)
        if self.get_account(tenant_id, account_id) is None:
            raise KeyError(account_id)
        store = get_session_store(self.settings, platform)
        path = store.save_dict(tenant_id, storage_state, account_id)
        status = store.login_status(tenant_id, account_id)
        return {"storage_state_path": str(path), **status}

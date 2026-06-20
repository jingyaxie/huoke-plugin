from app.core.config import Settings
from app.platforms.session_store import PlatformSessionStore

REQUIRED_LOGIN_COOKIES = {"sessionid", "sessionid_ss", "sid_tt", "sid_guard", "uid_tt", "uid_tt_ss"}
USER_LOGIN_MARKERS = {"login_time", "passport_assist_user"}


def _cookie_value(state: dict | None, name: str) -> str | None:
    if not state:
        return None
    for cookie in state.get("cookies") or []:
        if not isinstance(cookie, dict) or cookie.get("name") != name:
            continue
        value = str(cookie.get("value") or "").strip()
        return value or None
    return None


def _attach_platform_user_identity(result: dict, state: dict | None) -> None:
    uid = _cookie_value(state, "uid_tt")
    if not uid:
        return
    result["platform_user_id"] = uid
    result["uid"] = uid


class DouyinSessionStore(PlatformSessionStore):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings, platform="douyin")

    def is_ready(self, state: dict | None) -> bool:
        if not state:
            return False
        cookie_names = self._cookie_names(state)
        if cookie_names & REQUIRED_LOGIN_COOKIES:
            return True
        # 部分版本仅落盘用户登录标记 Cookie，仍视为可用。
        return bool(cookie_names & USER_LOGIN_MARKERS)

    def is_user_logged_in(self, state: dict | None) -> bool:
        """扫码登录用户；仅有 sessionid 的游客态返回 False。"""
        if not self.is_ready(state):
            return False
        return bool(self._cookie_names(state) & USER_LOGIN_MARKERS)

    @staticmethod
    def _cookie_names(state: dict | None) -> set[str]:
        if not state:
            return set()
        return {c.get("name") for c in state.get("cookies", []) if isinstance(c, dict) and c.get("name")}

    def _profile_satisfies_login_markers(self, cookie_names: set[str]) -> bool:
        # sessionid/uid_tt 在游客态也会出现，不能当作已登录 Profile。
        return bool(cookie_names & USER_LOGIN_MARKERS)

    def login_status(self, tenant_id: str, account_id: str = "default") -> dict:
        result = super().login_status(tenant_id, account_id=account_id)
        data = self.load(tenant_id, account_id) or {}
        if result.get("status") in {"ready", "incomplete"}:
            cookies = data.get("cookies") or []
            cookie_names = {c.get("name") for c in cookies if isinstance(c, dict)}
            result["required_cookies_present"] = sorted(cookie_names & REQUIRED_LOGIN_COOKIES)
        result["user_logged_in"] = self.is_user_logged_in(data)
        if result.get("status") == "ready" and result.get("user_logged_in"):
            _attach_platform_user_identity(result, data)
        return result

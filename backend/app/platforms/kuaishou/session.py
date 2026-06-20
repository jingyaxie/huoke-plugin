from app.core.config import Settings
from app.platforms.kuaishou.constants import REQUIRED_LOGIN_COOKIES
from app.platforms.session_store import PlatformSessionStore


class KuaishouSessionStore(PlatformSessionStore):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings, platform="kuaishou")

    def is_ready(self, state: dict | None) -> bool:
        if not state:
            return False
        cookie_names = {c.get("name") for c in state.get("cookies", []) if isinstance(c, dict)}
        return bool(cookie_names & REQUIRED_LOGIN_COOKIES)

    def _profile_satisfies_login_markers(self, cookie_names: set[str]) -> bool:
        return bool(cookie_names & REQUIRED_LOGIN_COOKIES)

    def login_status(self, tenant_id: str, account_id: str = "default") -> dict:
        result = super().login_status(tenant_id, account_id=account_id)
        if result.get("status") in {"ready", "incomplete"}:
            data = self.load(tenant_id, account_id=account_id) or {}
            cookies = data.get("cookies") or []
            cookie_names = {c.get("name") for c in cookies if isinstance(c, dict)}
            result["required_cookies_present"] = sorted(cookie_names & REQUIRED_LOGIN_COOKIES)
        return result

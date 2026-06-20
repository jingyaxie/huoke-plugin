from sqlalchemy.orm import Session

from app.platforms.constants import DEFAULT_PLATFORM


class BaseRepository:
    def __init__(self, session: Session, tenant_id: str = "default", platform: str = DEFAULT_PLATFORM) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.platform = platform

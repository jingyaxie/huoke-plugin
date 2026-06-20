from __future__ import annotations

from app.core.config import Settings
from app.platforms.douyin.crawler import DouyinCrawler
from app.platforms.douyin.session import DouyinSessionStore
from app.platforms.kuaishou.crawler import KuaishouCrawler
from app.platforms.kuaishou.session import KuaishouSessionStore
from app.platforms.session_store import PlatformSessionStore
from app.platforms.types import normalize_platform
from app.platforms.xiaohongshu.comments import XhsCommentCrawler
from app.platforms.xiaohongshu.crawler import XhsCrawler
from app.platforms.xiaohongshu.session import XhsSessionStore


def get_session_store(settings: Settings, platform: str) -> PlatformSessionStore:
    platform = normalize_platform(platform)
    if platform == "douyin":
        return DouyinSessionStore(settings)
    if platform == "xiaohongshu":
        return XhsSessionStore(settings)
    if platform == "kuaishou":
        return KuaishouSessionStore(settings)
    raise ValueError(f"平台 {platform} 尚未实现 SessionStore")


def get_hot_crawler(settings: Settings, platform: str, tenant_id: str, account_id: str = "default"):
    platform = normalize_platform(platform)
    store = get_session_store(settings, platform)
    if platform == "douyin":
        return DouyinCrawler(settings, tenant_id, store, account_id=account_id)
    if platform == "xiaohongshu":
        return XhsCrawler(settings, tenant_id, store, account_id=account_id)
    if platform == "kuaishou":
        return KuaishouCrawler(settings, tenant_id, store, account_id=account_id)
    raise ValueError(f"平台 {platform} 尚未实现热榜爬虫")


def get_search_tool(settings: Settings, platform: str, tenant_id: str, account_id: str = "default"):
    platform = normalize_platform(platform)
    store = get_session_store(settings, platform)
    if platform == "douyin":
        from app.platforms.douyin.search import DouyinSearchTool

        return DouyinSearchTool(settings, tenant_id, store, account_id=account_id)
    if platform == "xiaohongshu":
        from app.platforms.xiaohongshu.search import XhsSearchTool

        return XhsSearchTool(settings, tenant_id, store, account_id=account_id)
    if platform == "kuaishou":
        from app.platforms.kuaishou.search import KuaishouSearchTool

        return KuaishouSearchTool(settings, tenant_id, store, account_id=account_id)
    raise ValueError(f"平台 {platform} 尚未实现搜索工具")


def get_comment_tool(settings: Settings, platform: str, tenant_id: str, account_id: str = "default"):
    platform = normalize_platform(platform)
    store = get_session_store(settings, platform)
    if platform == "douyin":
        from app.platforms.douyin.comment_tool import DouyinCommentTool

        return DouyinCommentTool(settings, tenant_id, store, account_id=account_id)
    if platform == "xiaohongshu":
        from app.platforms.xiaohongshu.comment_tool import XhsCommentTool

        return XhsCommentTool(settings, tenant_id, store, account_id=account_id)
    if platform == "kuaishou":
        from app.platforms.kuaishou.comment_tool import KuaishouCommentTool

        return KuaishouCommentTool(settings, tenant_id, store, account_id=account_id)
    raise ValueError(f"平台 {platform} 尚未实现评论工具")


def get_follow_tool(settings: Settings, platform: str, tenant_id: str, account_id: str = "default"):
    platform = normalize_platform(platform)
    store = get_session_store(settings, platform)
    if platform == "douyin":
        from app.platforms.douyin.follow import DouyinFollowTool

        return DouyinFollowTool(settings, tenant_id, store, account_id=account_id)
    if platform == "xiaohongshu":
        raise NotImplementedError(
            "小红书 Direct API 关注已移除，请使用 warm_outreach（follow-user + warm_outreach=true + 浏览器 page）"
        )
    if platform == "kuaishou":
        from app.platforms.kuaishou.follow import KuaishouFollowTool

        return KuaishouFollowTool(settings, tenant_id, store, account_id=account_id)
    raise ValueError(f"平台 {platform} 尚未实现关注工具")


def get_dm_tool(settings: Settings, platform: str, tenant_id: str, account_id: str = "default"):
    platform = normalize_platform(platform)
    store = get_session_store(settings, platform)
    if platform == "douyin":
        from app.platforms.douyin.dm import DouyinDmTool

        return DouyinDmTool(settings, tenant_id, store, account_id=account_id)
    if platform == "xiaohongshu":
        from app.platforms.xiaohongshu.dm import XhsDmTool

        return XhsDmTool(settings, tenant_id, store, account_id=account_id)
    if platform == "kuaishou":
        from app.platforms.kuaishou.dm import KuaishouDmTool

        return KuaishouDmTool(settings, tenant_id, store, account_id=account_id)
    raise ValueError(f"平台 {platform} 尚未实现私信工具")


def get_reply_comment_tool(settings: Settings, platform: str, tenant_id: str, account_id: str = "default"):
    platform = normalize_platform(platform)
    store = get_session_store(settings, platform)
    if platform == "douyin":
        from app.platforms.douyin.reply_comment import DouyinReplyCommentTool

        return DouyinReplyCommentTool(settings, tenant_id, store, account_id=account_id)
    if platform == "xiaohongshu":
        raise NotImplementedError(
            "小红书 Direct API 回复已移除，请使用 warm_publish（reply-comment + warm_publish=true + 浏览器 page）"
        )
    if platform == "kuaishou":
        from app.platforms.kuaishou.reply_comment import KuaishouReplyCommentTool

        return KuaishouReplyCommentTool(settings, tenant_id, store, account_id=account_id)
    raise ValueError(f"平台 {platform} 尚未实现回复评论工具")


def get_qr_login_tool(settings: Settings, platform: str, tenant_id: str, account_id: str = "default"):
    platform = normalize_platform(platform)
    store = get_session_store(settings, platform)
    if platform == "douyin":
        from app.platforms.douyin.qr_login import DouyinQrLoginTool

        return DouyinQrLoginTool(settings, tenant_id, store, account_id=account_id)
    if platform == "xiaohongshu":
        from app.platforms.xiaohongshu.qr_login import XhsQrLoginTool

        return XhsQrLoginTool(settings, tenant_id, store, account_id=account_id)
    if platform == "kuaishou":
        from app.platforms.kuaishou.qr_login import KuaishouQrLoginTool

        return KuaishouQrLoginTool(settings, tenant_id, store, account_id=account_id)
    raise ValueError(f"平台 {platform} 尚未实现二维码登录")


def get_account_dashboard_tool(settings: Settings, platform: str, tenant_id: str, account_id: str = "default"):
    platform = normalize_platform(platform)
    store = get_session_store(settings, platform)
    if platform == "douyin":
        from app.platforms.douyin.account_dashboard import DouyinAccountDashboardTool

        return DouyinAccountDashboardTool(settings, tenant_id, store, account_id=account_id)
    if platform == "xiaohongshu":
        from app.platforms.xiaohongshu.account_dashboard import XhsAccountDashboardTool

        return XhsAccountDashboardTool(settings, tenant_id, store, account_id=account_id)
    if platform == "kuaishou":
        from app.platforms.kuaishou.account_dashboard import KuaishouAccountDashboardTool

        return KuaishouAccountDashboardTool(settings, tenant_id, store, account_id=account_id)
    raise ValueError(f"平台 {platform} 尚未实现账号主页监控")


def get_comment_crawler(settings: Settings, platform: str, tenant_id: str, account_id: str = "default"):
    platform = normalize_platform(platform)
    store = get_session_store(settings, platform)
    if platform == "douyin":
        from app.platforms.douyin.comments import DouyinCommentCrawler

        return DouyinCommentCrawler(settings, tenant_id, store, account_id=account_id)
    if platform == "xiaohongshu":
        return XhsCommentCrawler(settings, tenant_id, store, account_id=account_id)
    if platform == "kuaishou":
        from app.platforms.kuaishou.comments import KuaishouCommentCrawler

        return KuaishouCommentCrawler(settings, tenant_id, store, account_id=account_id)
    raise ValueError(f"平台 {platform} 尚未实现评论爬虫")


def list_platforms() -> list[dict]:
    return [
        {
            "id": "douyin",
            "name": "抖音",
            "capabilities": ["hot", "comments", "login", "qr_login", "keyword_search", "follow", "dm", "reply_comment", "account_dashboard"],
        },
        {
            "id": "xiaohongshu",
            "name": "小红书",
            "capabilities": ["hot", "comments", "login", "qr_login", "keyword_search", "follow", "dm", "reply_comment", "account_dashboard"],
        },
        {
            "id": "kuaishou",
            "name": "快手",
            "capabilities": ["hot", "comments", "login", "qr_login", "keyword_search", "follow", "dm", "reply_comment", "account_bind", "account_dashboard"],
        },
    ]

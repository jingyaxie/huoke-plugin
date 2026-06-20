from __future__ import annotations


def parse_douyin_account(raw_profile: dict, raw_works: dict, raw_notice: dict, raw_im: dict) -> dict:
    user = raw_profile.get("user") or raw_profile.get("user_info") or {}
    avatar = ""
    avatar_obj = user.get("avatar_larger") or user.get("avatar_medium") or user.get("avatar_thumb")
    if isinstance(avatar_obj, dict):
        urls = avatar_obj.get("url_list") or []
        avatar = urls[0] if urls else ""

    account = {
        "nickname": user.get("nickname") or "",
        "user_id": str(user.get("uid") or user.get("short_id") or ""),
        "sec_uid": user.get("sec_uid") or "",
        "unique_id": user.get("unique_id") or "",
        "avatar": avatar,
        "signature": user.get("signature") or "",
        "follower_count": user.get("follower_count") or 0,
        "following_count": user.get("following_count") or 0,
        "aweme_count": user.get("aweme_count") or 0,
        "total_favorited": user.get("total_favorited") or 0,
        "favoriting_count": user.get("favoriting_count") or 0,
    }

    works = []
    for item in raw_works.get("aweme_list") or []:
        stats = item.get("statistics") or {}
        aweme_id = item.get("aweme_id") or ""
        works.append(
            {
                "id": aweme_id,
                "title": item.get("desc") or "",
                "create_time": item.get("create_time"),
                "play_count": stats.get("play_count") or 0,
                "digg_count": stats.get("digg_count") or 0,
                "comment_count": stats.get("comment_count") or 0,
                "share_count": stats.get("share_count") or 0,
                "url": f"https://www.douyin.com/video/{aweme_id}" if aweme_id else "",
            }
        )

    notice = raw_notice.get("notice_count") or raw_notice.get("notice") or raw_notice
    if isinstance(notice, list):
        notice = {item.get("type") or item.get("name"): item.get("count") or item.get("value") for item in notice if isinstance(item, dict)}
    if not isinstance(notice, dict):
        notice = {}
    notifications = {
        "follower": notice.get("follower_count") or notice.get("follower") or 0,
        "comment": notice.get("comment_count") or notice.get("comment") or 0,
        "digg": notice.get("digg_count") or notice.get("digg") or 0,
        "mention": notice.get("mention_count") or notice.get("at") or 0,
        "total_unread": notice.get("total") or notice.get("total_unread") or 0,
    }

    conversations = []
    for conv in (raw_im.get("spotlight") or raw_im.get("conversations") or raw_im.get("data") or [])[:10]:
        if not isinstance(conv, dict):
            continue
        peer = conv.get("user") or conv.get("core_info") or conv.get("peer_user") or {}
        conversations.append(
            {
                "conversation_id": conv.get("conversation_id") or conv.get("conv_id") or "",
                "nickname": peer.get("nickname") or peer.get("nick_name") or "",
                "unread_count": conv.get("unread_count") or 0,
                "last_message": conv.get("last_message") or conv.get("content") or "",
            }
        )
    im = {
        "unread_count": raw_im.get("total_unread") or sum(c["unread_count"] for c in conversations),
        "conversations": conversations,
    }

    return {"account": account, "notifications": notifications, "im": im, "works": works}


def parse_xhs_account(raw_self: dict, raw_notes: dict, raw_mentions: dict) -> dict:
    data = raw_self.get("data") or raw_self
    basic = data.get("basic_info") or data.get("user") or data
    interact = data.get("interact_info") or data.get("interactions") or {}

    account = {
        "nickname": basic.get("nickname") or basic.get("name") or "",
        "user_id": basic.get("user_id") or basic.get("id") or "",
        "red_id": basic.get("red_id") or "",
        "avatar": basic.get("image") or basic.get("avatar") or "",
        "signature": basic.get("desc") or basic.get("signature") or "",
        "follower_count": interact.get("follower_count") or basic.get("fans") or 0,
        "following_count": interact.get("follows_count") or basic.get("follows") or 0,
        "note_count": interact.get("note_count") or basic.get("note_count") or 0,
        "liked_count": interact.get("liked_count") or basic.get("liked_count") or 0,
        "collected_count": interact.get("collected_count") or 0,
    }

    notes = []
    note_list = raw_notes.get("data") or raw_notes.get("notes") or []
    if isinstance(note_list, dict):
        note_list = note_list.get("notes") or note_list.get("items") or []
    for item in note_list:
        if not isinstance(item, dict):
            continue
        note_card = item.get("note_card") or item
        interact_info = note_card.get("interact_info") or item.get("interact_info") or {}
        note_id = note_card.get("note_id") or item.get("id") or ""
        notes.append(
            {
                "id": note_id,
                "title": note_card.get("display_title") or note_card.get("title") or "",
                "create_time": note_card.get("time") or item.get("time"),
                "liked_count": interact_info.get("liked_count") or 0,
                "comment_count": interact_info.get("comment_count") or 0,
                "collected_count": interact_info.get("collected_count") or 0,
                "url": f"https://www.xiaohongshu.com/explore/{note_id}" if note_id else "",
            }
        )

    mention_data = raw_mentions.get("data") or raw_mentions
    notifications = {
        "mentions": mention_data.get("mention_count") or mention_data.get("total") or 0,
        "likes": mention_data.get("like_count") or 0,
        "follows": mention_data.get("follow_count") or 0,
        "total_unread": mention_data.get("unread_count") or mention_data.get("total") or 0,
        "items": (mention_data.get("items") or mention_data.get("messages") or [])[:10],
    }

    return {"account": account, "notifications": notifications, "im": {"unread_count": 0, "conversations": []}, "works": notes}


def parse_kuaishou_account(raw_profile: dict, raw_works: dict) -> dict:
    profile = raw_profile.get("userProfile") or raw_profile.get("profile") or raw_profile
    owner = profile.get("owner") or profile.get("user") or profile
    counts = profile.get("counts") or owner.get("counts") or {}

    account = {
        "nickname": owner.get("name") or owner.get("user_name") or "",
        "user_id": str(owner.get("id") or owner.get("user_id") or ""),
        "avatar": owner.get("headerUrl") or owner.get("headurl") or "",
        "signature": owner.get("description") or owner.get("user_text") or "",
        "follower_count": counts.get("fan") or owner.get("fan") or 0,
        "following_count": counts.get("follow") or owner.get("follow") or 0,
        "photo_count": counts.get("photo") or owner.get("photo") or 0,
        "liked_count": counts.get("liked") or owner.get("liked") or 0,
    }

    works = []
    feed_data = raw_works.get("data") or raw_works
    feeds = feed_data.get("visionProfilePhotoList", {}).get("feeds") if isinstance(feed_data, dict) else []
    if not feeds and isinstance(feed_data, dict):
        feeds = feed_data.get("feeds") or []
    for item in feeds:
        if not isinstance(item, dict):
            continue
        photo = item.get("photo") or item
        photo_id = photo.get("id") or photo.get("photoId") or ""
        works.append(
            {
                "id": photo_id,
                "title": photo.get("caption") or "",
                "create_time": photo.get("timestamp"),
                "play_count": photo.get("viewCount") or photo.get("view_count") or 0,
                "digg_count": photo.get("likeCount") or photo.get("like_count") or 0,
                "comment_count": photo.get("commentCount") or photo.get("comment_count") or 0,
                "url": f"https://www.kuaishou.com/short-video/{photo_id}" if photo_id else "",
            }
        )

    return {
        "account": account,
        "notifications": {"total_unread": 0, "follower": 0, "comment": 0, "digg": 0},
        "im": {"unread_count": 0, "conversations": []},
        "works": works,
    }

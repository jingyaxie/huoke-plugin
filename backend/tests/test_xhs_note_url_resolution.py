from __future__ import annotations

from app.platforms.xiaohongshu.utils import build_note_url, extract_note_access_params, resolve_note_open_url

USER_NOTE_URL = (
    "https://www.xiaohongshu.com/explore/6a1e6114000000002003b64f"
    "?xsec_token=ABk6U0Y3MsNhMO4R5OlBOQV2J2ijfRBIfE5EDVvrSX8cQ="
    "&xsec_source=pc_search&source=web_explore_feed"
)
NOTE_ID = "6a1e6114000000002003b64f"
TOKEN = "ABk6U0Y3MsNhMO4R5OlBOQV2J2ijfRBIfE5EDVvrSX8cQ="


def test_build_note_url_without_token_is_incomplete():
    bare = build_note_url(NOTE_ID, None, "pc_search")
    assert NOTE_ID in bare
    assert "xsec_source=pc_search" in bare
    assert "xsec_token=" not in bare


def test_resolve_note_open_url_prefers_full_content_url():
    resolved = resolve_note_open_url(NOTE_ID, content_url=USER_NOTE_URL)
    access = extract_note_access_params(resolved)
    assert access.get("xsec_token") == TOKEN
    assert access.get("xsec_source") == "pc_search"


def test_resolve_note_open_url_reads_token_from_meta():
    resolved = resolve_note_open_url(
        NOTE_ID,
        note_meta={"note_id": NOTE_ID, "xsec_token": TOKEN, "xsec_source": "pc_feed"},
    )
    assert extract_note_access_params(resolved).get("xsec_token") == TOKEN

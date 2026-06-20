from app.platforms.xiaohongshu.js_constants import _is_search_result_api


def test_is_search_result_api_accepts_v2_so_domain():
    assert _is_search_result_api("https://so.xiaohongshu.com/api/sns/web/v2/search/notes")


def test_is_search_result_api_accepts_v1_edith():
    assert _is_search_result_api("https://edith.xiaohongshu.com/api/sns/web/v1/search/notes")


def test_is_search_result_api_rejects_suggest():
    assert not _is_search_result_api("https://so.xiaohongshu.com/api/sns/web/v1/search/suggest")

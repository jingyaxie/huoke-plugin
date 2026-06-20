from app.utils.parsers import parse_count, parse_datetime


def test_parse_count():
    assert parse_count("1.2万") == 12000
    assert parse_count("3亿") == 300000000
    assert parse_count("12,345") == 12345


def test_parse_datetime():
    assert parse_datetime("2026-05-30 12:34:56").year == 2026
    assert parse_datetime("2026/05/30 12:34").month == 5


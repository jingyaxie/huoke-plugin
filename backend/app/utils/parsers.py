import re
from datetime import datetime
from typing import Optional, Union


COUNT_PATTERN = re.compile(r"([0-9]+(?:\.[0-9]+)?)([万亿]?)")


def parse_count(value: Optional[Union[str, int, float]]) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "").replace(" ", "")
    if not text:
        return 0
    match = COUNT_PATTERN.search(text)
    if not match:
        return 0
    number = float(match.group(1))
    unit = match.group(2)
    if unit == "万":
        number *= 10000
    elif unit == "亿":
        number *= 100000000
    return int(number)


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = value.strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None

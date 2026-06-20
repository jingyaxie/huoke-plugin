import json

from app.services.message_payload_normalizer import understand_task_message


def test_understand_task_create_request_wrapper():
    raw = {
        "template_id": "lead-crawl",
        "name": "深圳餐饮老板线索",
        "spec": {
            "keyword": "团餐配送",
            "platform": "douyin",
            "region": "深圳",
            "crawl": {"comment_days": 3, "target_leads": 50},
        },
    }
    understood = understand_task_message(json.dumps(raw, ensure_ascii=False))
    assert understood is not None
    assert understood.source == "task_create_request"
    assert understood.payload["keyword"] == "团餐配送"
    assert understood.payload["target_count"] == 50


def test_understand_natural_language():
    understood = understand_task_message("抓取抖音关键词团餐配送，目标20条")
    assert understood is not None
    assert understood.source == "inferred"
    assert understood.payload["keyword"] == "团餐配送"
    assert understood.payload["platform"] == "douyin"
    assert understood.payload["target_count"] == 20

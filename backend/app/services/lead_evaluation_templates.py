"""租户级线索评估模板（行业预设）。"""
from __future__ import annotations

from typing import Any

EVALUATION_TEMPLATES: dict[str, dict[str, Any]] = {
    "home_renovation": {
        "label": "家装建材",
        "target_customer": "有装修、改造需求的本地业主",
        "product_or_service": "建材/定制安装服务",
        "accept_description": "评论者对装修/建材类内容表现出咨询、询价、预约或购买意向",
        "reject_description": "同行广告、招聘、与业务无关的灌水",
    },
    "catering_b2b": {
        "label": "餐饮团餐",
        "target_customer": "需要团餐、配送、食堂承包的企业采购",
        "product_or_service": "团餐配送/食堂承包",
        "accept_description": "咨询团餐价格、配送范围、起订量、合作方式",
        "reject_description": "求职者、无关美食讨论、同行广告",
        "positive_examples": ["公司团餐怎么收费", "能配送吗"],
        "negative_examples": ["还招人吗", "好吃"],
    },
    "beauty_salon": {
        "label": "美业门店",
        "target_customer": "有美容、护理、到店消费意向的用户",
        "product_or_service": "美容护理/到店服务",
        "accept_description": "询价、预约到店、咨询项目效果、问地址电话",
        "reject_description": "同行、招聘、无关闲聊",
        "positive_examples": ["怎么预约", "单次多少钱"],
        "negative_examples": ["招美甲师"],
    },
    "general_leads": {
        "label": "通用获客",
        "accept_description": "评论语义与获客主题相符，存在咨询、询价、预约或真实兴趣表达",
        "reject_description": "同行广告、招聘、与视频主题无关的灌水",
    },
}


def list_evaluation_templates() -> list[dict[str, Any]]:
    return [
        {"id": tid, **{k: v for k, v in meta.items() if k != "label"}, "label": meta.get("label", tid)}
        for tid, meta in EVALUATION_TEMPLATES.items()
    ]


def resolve_evaluation_template(template_id: str | None) -> dict[str, Any]:
    tid = str(template_id or "").strip()
    if not tid:
        return {}
    meta = EVALUATION_TEMPLATES.get(tid)
    if not isinstance(meta, dict):
        return {}
    return {"template_id": tid, **dict(meta)}

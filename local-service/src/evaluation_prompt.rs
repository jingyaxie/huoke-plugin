use crate::job_config::EvaluationConfig;

pub const SYSTEM_PROMPT: &str = r#"你是社交媒体评论线索评估助手。严格按任务给定的「线索识别标准」判断每条评论是否为精准客户。
只输出 JSON，格式：{"results":[{"comment_id":"...","is_precise":true/false,"reason":"简短中文说明","score":0.0-1.0}]}
规则：
- is_precise=true（精准客户）：评论与任务意图/评估标准吻合，表现出咨询、购买意向、使用需求、询价、预约，或像真实用户分享与产品相关的心得与痛点
- is_precise=false：无关内容、纯表情、同行广告、招聘、明显 spam、与任务完全无关
- reason 用一句话说明判断依据（引用评论中的关键信号）
- score 表示匹配度 0~1
- 必须为每条输入评论返回一条结果，comment_id 与输入完全一致"#;

pub struct EvalCommentInput<'a> {
    pub comment_id: &'a str,
    pub content: &'a str,
}

fn uses_experience_mode(eval_cfg: &EvaluationConfig) -> bool {
    eval_cfg.target_customer.as_ref().is_none_or(|s| s.trim().is_empty())
        && eval_cfg
            .accept_description
            .as_ref()
            .is_none_or(|s| s.trim().is_empty())
}

pub fn build_user_prompt(
    keyword: &str,
    eval_cfg: &EvaluationConfig,
    comments: &[EvalCommentInput<'_>],
) -> String {
    let product = eval_cfg
        .product_or_service
        .as_deref()
        .filter(|s| !s.is_empty())
        .unwrap_or(keyword);
    let experience_mode = uses_experience_mode(eval_cfg);
    let target = eval_cfg
        .target_customer
        .as_deref()
        .filter(|s| !s.is_empty())
        .unwrap_or("未指定，请根据产品/服务推断");
    let accept = eval_cfg
        .accept_description
        .as_deref()
        .filter(|s| !s.is_empty())
        .unwrap_or(if experience_mode {
            "像真实用户分享与产品/服务相关的使用心得、体验感受，或表达咨询/购买意向、询问价格/效果/购买方式、描述自身需求或痛点"
        } else {
            "表达购买意向、咨询价格/联系方式、分享使用需求或痛点"
        });
    let reject = if eval_cfg.reject_signals.is_empty() {
        "同行广告、招聘、纯表情、无实质内容、与产品无关的闲聊".to_string()
    } else {
        eval_cfg.reject_signals.join("、")
    };

    let mut lines = vec![
        "## 线索识别标准".to_string(),
        format!("产品/服务：{product}"),
        format!("搜索关键词：{keyword}"),
        format!("目标客户：{target}"),
        format!("有效线索特征：{accept}"),
        format!("排除信号：{reject}"),
    ];
    if experience_mode {
        lines.push(String::new());
        lines.push("## 评估模式".to_string());
        lines.push(
            "未填写自定义标准，采用「使用心得」模式：优先识别像真实潜在客户的评论（体验分享、需求表达、咨询意向），排除灌水与无关内容。"
                .to_string(),
        );
    }
    lines.push(String::new());
    lines.push("## 待评估评论".to_string());

    for (idx, comment) in comments.iter().enumerate() {
        let display = truncate_chars(comment.content.trim(), 200);
        lines.push(format!(
            "{}. [comment_id:{}] {}",
            idx + 1,
            comment.comment_id,
            display
        ));
    }

    lines.join("\n")
}

pub fn truncate_chars(text: &str, max_chars: usize) -> String {
    if text.chars().count() <= max_chars {
        return text.to_string();
    }
    let trimmed: String = text.chars().take(max_chars).collect();
    format!("{trimmed}…")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::job_config::EvaluationConfig;

    #[test]
    fn truncate_chars_respects_utf8_boundary() {
        let text = "以".repeat(120);
        let out = truncate_chars(&text, 100);
        assert!(out.ends_with('…'));
        assert!(out.chars().count() <= 101);
    }

    #[test]
    fn build_prompt_includes_comments() {
        let comments = vec![EvalCommentInput {
            comment_id: "c1",
            content: "想咨询一下价格",
        }];
        let cfg = EvaluationConfig {
            product_or_service: Some("团餐".into()),
            target_customer: None,
            accept_description: None,
            reject_signals: vec![],
        };
        let prompt = build_user_prompt("团餐", &cfg, &comments);
        assert!(prompt.contains("comment_id:c1"));
        assert!(prompt.contains("想咨询一下价格"));
    }

    #[test]
    fn build_prompt_uses_experience_mode_by_default() {
        let cfg = EvaluationConfig {
            product_or_service: Some("团餐".into()),
            target_customer: None,
            accept_description: None,
            reject_signals: vec![],
        };
        let prompt = build_user_prompt("团餐", &cfg, &[]);
        assert!(prompt.contains("使用心得"));
        assert!(prompt.contains("线索识别标准"));
    }
}

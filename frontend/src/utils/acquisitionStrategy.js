/** 抖音获客执行策略（与后端 agent_strategy/registry 对齐） */

export const STRATEGY_SKILL_FLOW_DOUYIN = "skill-flow-douyin";
export const STRATEGY_STANDALONE_DOUYIN = "standalone-browse-douyin";
export const STRATEGY_SKILL_FLOW_XHS = "skill-flow-xiaohongshu";

const FALLBACK_BY_PLATFORM = {
  douyin: STRATEGY_SKILL_FLOW_DOUYIN,
  xiaohongshu: STRATEGY_SKILL_FLOW_XHS,
};

export function defaultAgentStrategyForPlatform(platform) {
  return FALLBACK_BY_PLATFORM[String(platform || "").trim().toLowerCase()] || STRATEGY_SKILL_FLOW_DOUYIN;
}

export function resolveAgentStrategy(platform, strategyId) {
  const resolved = String(strategyId || "").trim();
  if (resolved) return resolved;
  return defaultAgentStrategyForPlatform(platform);
}

export function isStandaloneDouyinStrategy(strategyId) {
  return String(strategyId || "").trim() === STRATEGY_STANDALONE_DOUYIN;
}

export function strategyAvailableForPlatform(platform, strategyId) {
  const plat = String(platform || "").trim().toLowerCase();
  if (plat === "douyin") {
    return [STRATEGY_SKILL_FLOW_DOUYIN, STRATEGY_STANDALONE_DOUYIN].includes(strategyId);
  }
  if (plat === "xiaohongshu") {
    return strategyId === STRATEGY_SKILL_FLOW_XHS;
  }
  return false;
}

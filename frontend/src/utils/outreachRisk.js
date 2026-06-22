import { ElMessageBox } from "element-plus";

export const OUTREACH_RISK_UNAVAILABLE_MSG = "检测到有风控风险，评论关注暂未触达";

/** 触达数为 0 时弹风控提示，返回 true 表示已拦截 */
export async function alertOutreachRiskIfZero(count) {
  if (Number(count || 0) > 0) return false;
  await ElMessageBox.alert(OUTREACH_RISK_UNAVAILABLE_MSG, "提示", {
    confirmButtonText: "知道了",
    type: "warning",
  });
  return true;
}

/** content 回退：私信发送必须在 background 通过 CDP 完成 */
export async function sendDm() {
  return {
    ok: false,
    mode: "content_fallback",
    url: location.href,
    message: "请重新加载扩展以启用 CDP 发送私信（真实鼠标点击或 Enter）",
  };
}

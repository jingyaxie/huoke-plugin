/** 平台页是否处于验证码 / 风控中间页，不宜作为实验室工作标签 */
export function isBlockedPlatformPage(tab: Pick<chrome.tabs.Tab, "url" | "title">): boolean {
  const title = String(tab.title ?? "");
  const url = String(tab.url ?? "");
  if (/验证码|captcha|安全验证|risk|verify/i.test(title)) return true;
  if (/captcha|verify|security|bytecheck|sec_did/i.test(url)) return true;
  return false;
}

export function isUsablePlatformTab(tab: Pick<chrome.tabs.Tab, "id" | "url" | "title">): boolean {
  if (!tab.id || !tab.url) return false;
  if (tab.url.startsWith("chrome://") || tab.url.startsWith("chrome-error://")) return false;
  return !isBlockedPlatformPage(tab);
}

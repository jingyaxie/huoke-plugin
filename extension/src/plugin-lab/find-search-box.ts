import {
  activateSearchInput,
  describeSearchInput,
  detectPlatformFromUrl,
  findSearchInputMatch,
  waitForSearchInput,
} from "./search-input";

export interface FindSearchBoxPayload {
  platform?: string;
}

export async function findSearchBox(payload: FindSearchBoxPayload = {}) {
  const platform =
    payload.platform && payload.platform !== "unknown"
      ? (payload.platform as ReturnType<typeof detectPlatformFromUrl>)
      : detectPlatformFromUrl();

  const match = (await waitForSearchInput(platform, 8, 500)) ?? findSearchInputMatch(platform);
  if (!match) {
    return {
      found: false,
      platform,
      url: location.href,
      expected_selector: 'input[data-e2e="searchbar-input"]',
      message: `未找到 ${platform} 搜索框，请确认页面已加载完成`,
    };
  }

  const info = describeSearchInput(match, platform);
  return {
    ...info,
    message: `已找到搜索框：${info.selector}`,
  };
}

export async function findAndFocusSearchBox(payload: FindSearchBoxPayload = {}) {
  const result = await findSearchBox(payload);
  if (!result.found) return result;

  const platform =
    payload.platform && payload.platform !== "unknown"
      ? (payload.platform as ReturnType<typeof detectPlatformFromUrl>)
      : detectPlatformFromUrl();

  const match = findSearchInputMatch(platform);
  if (!match) return result;

  await activateSearchInput(match.input);
  const info = describeSearchInput(match, platform);
  return {
    ...info,
    focused: true,
    value: match.input.value ?? "",
    message: `已找到并聚焦搜索框：${info.selector}`,
  };
}

import PCA_REGIONS from "./chinaRegionsPca.json";

/** 中国省级行政区（首项默认不选地区） */
export const REGION_OPTIONS = [
  { code: "", name: "不选地区" },
  { code: "11", name: "北京" },
  { code: "12", name: "天津" },
  { code: "13", name: "河北" },
  { code: "14", name: "山西" },
  { code: "15", name: "内蒙古" },
  { code: "21", name: "辽宁" },
  { code: "22", name: "吉林" },
  { code: "23", name: "黑龙江" },
  { code: "31", name: "上海" },
  { code: "32", name: "江苏" },
  { code: "33", name: "浙江" },
  { code: "34", name: "安徽" },
  { code: "35", name: "福建" },
  { code: "36", name: "江西" },
  { code: "37", name: "山东" },
  { code: "41", name: "河南" },
  { code: "42", name: "湖北" },
  { code: "43", name: "湖南" },
  { code: "44", name: "广东" },
  { code: "45", name: "广西" },
  { code: "46", name: "海南" },
  { code: "50", name: "重庆" },
  { code: "51", name: "四川" },
  { code: "52", name: "贵州" },
  { code: "53", name: "云南" },
  { code: "54", name: "西藏" },
  { code: "61", name: "陕西" },
  { code: "62", name: "甘肃" },
  { code: "63", name: "青海" },
  { code: "64", name: "宁夏" },
  { code: "65", name: "新疆" },
  { code: "71", name: "台湾" },
  { code: "81", name: "香港" },
  { code: "82", name: "澳门" },
];

export function findRegionOption(code) {
  const key = String(code ?? "").trim();
  return REGION_OPTIONS.find((row) => row.code === key) || null;
}

export function regionLabelFromCode(code) {
  const key = String(code ?? "").trim();
  if (!key) return "";
  const direct = findRegionOption(key);
  if (direct) return direct.name;
  // 兼容旧任务里存的市/区级 code，回退到省级
  if (key.length > 2) {
    return findRegionOption(key.slice(0, 2))?.name || "";
  }
  return "";
}

export function isNoRegion(nameOrCode) {
  const text = String(nameOrCode ?? "").trim();
  return !text || text === "不选地区" || text === "不限地区" || text === "全国";
}

/* ------------------------------------------------------------------ *
 * 省 / 市 / 区县 三级联动（数据源参考 AI 移动端 china_regions_pca.json）
 * 数据结构：{ "86": {省code: 省名}, 省code: {市code: 市名}, 市code: {区县code: 区县名} }
 * ------------------------------------------------------------------ */
const PCA_ROOT_CODE = "86";
const PLACEHOLDER_REGION_NAMES = new Set([
  "市辖区",
  "县",
  "省直辖县级行政区划",
  "自治区直辖县级行政区划",
]);

/** 占位行政名（如「市辖区」）显示为空，交由上级名称兜底 */
function displayRegionName(raw) {
  const text = String(raw ?? "").trim();
  return PLACEHOLDER_REGION_NAMES.has(text) ? "" : text;
}

function pcaChildrenOf(parentCode) {
  const map = PCA_REGIONS[parentCode];
  if (!map) return [];
  return Object.entries(map)
    .map(([code, name]) => ({ code, name: String(name).trim() }))
    .filter((row) => row.name)
    .sort((a, b) => a.code.localeCompare(b.code));
}

let cascaderCache = null;
/** Element Plus el-cascader 选项树（省 → 市 → 区县） */
export function buildRegionCascaderOptions() {
  if (cascaderCache) return cascaderCache;
  cascaderCache = pcaChildrenOf(PCA_ROOT_CODE).map((province) => {
    const provinceNode = { value: province.code, label: province.name };
    const cities = pcaChildrenOf(province.code);
    if (cities.length) {
      provinceNode.children = cities.map((city) => {
        const cityLabel = displayRegionName(city.name) || province.name;
        const cityNode = { value: city.code, label: cityLabel };
        const districts = pcaChildrenOf(city.code).filter((d) => displayRegionName(d.name));
        if (districts.length) {
          cityNode.children = districts.map((d) => ({
            value: d.code,
            label: displayRegionName(d.name),
          }));
        }
        return cityNode;
      });
    }
    return provinceNode;
  });
  return cascaderCache;
}

export const REGION_CASCADER_OPTIONS = buildRegionCascaderOptions();

/**
 * 由级联路径（code 数组）解析出地区信息。
 * @returns {{ code: string, name: string, fullName: string }}
 *   code     - 最末一级的行政区 code
 *   name     - 最末一级名称（用于「最后的城市名称」搜索）
 *   fullName - 完整路径，如「江苏省 南通市 通州区」（用于展示）
 */
export function regionSelectionFromPath(path) {
  const codes = (Array.isArray(path) ? path : [path]).map((c) => String(c ?? "").trim()).filter(Boolean);
  if (!codes.length) return { code: "", name: "", fullName: "" };
  let nodes = REGION_CASCADER_OPTIONS;
  const labels = [];
  let leafCode = "";
  for (const code of codes) {
    const node = nodes.find((n) => n.value === code);
    if (!node) break;
    labels.push(node.label);
    leafCode = node.value;
    nodes = node.children || [];
  }
  return {
    code: leafCode,
    name: labels[labels.length - 1] || "",
    fullName: labels.join(" "),
  };
}

/**
 * 搜索词地区前缀：只取「最后一级城市名」并去掉行政后缀，
 * 避免把全路径（如「江苏省 南通市 通州区」）拼进搜索词导致搜不到内容。
 */
export function regionSearchToken(regionName) {
  const text = String(regionName ?? "").trim();
  if (isNoRegion(text)) return "";
  const leaf = text
    .split(/[\s·]+/)
    .map((s) => s.trim())
    .filter(Boolean)
    .pop();
  if (!leaf) return "";
  return leaf
    .replace(/(维吾尔自治区|壮族自治区|回族自治区|特别行政区|自治区|自治州|自治县|地区|林区)$/u, "")
    .replace(/(省|市|区|县|旗|盟)$/u, "");
}

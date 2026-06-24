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

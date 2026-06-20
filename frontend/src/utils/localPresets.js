const STORAGE_KEY = "huoke_local_presets_v1";

const DEFAULT_PRESETS = {
  comments: [],
  "dm-openers": [],
};

function loadStore() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_PRESETS };
    const parsed = JSON.parse(raw);
    return {
      comments: Array.isArray(parsed.comments) ? parsed.comments : [],
      "dm-openers": Array.isArray(parsed["dm-openers"]) ? parsed["dm-openers"] : [],
    };
  } catch {
    return { ...DEFAULT_PRESETS };
  }
}

function saveStore(store) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
}

function makeId() {
  return `local_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

export function listLocalPresets(kind) {
  const store = loadStore();
  return { items: [...(store[kind] || [])] };
}

export function createLocalPreset(kind, payload) {
  const store = loadStore();
  const now = new Date().toISOString();
  const row = {
    id: makeId(),
    name: String(payload.name || "").trim(),
    content: String(payload.content || "").trim(),
    created_at: now,
    updated_at: now,
  };
  store[kind] = [row, ...(store[kind] || [])];
  saveStore(store);
  return row;
}

export function updateLocalPreset(kind, presetId, payload) {
  const store = loadStore();
  const rows = store[kind] || [];
  const index = rows.findIndex((row) => row.id === presetId);
  if (index < 0) throw new Error("预设不存在");
  rows[index] = {
    ...rows[index],
    name: String(payload.name ?? rows[index].name).trim(),
    content: String(payload.content ?? rows[index].content).trim(),
    updated_at: new Date().toISOString(),
  };
  store[kind] = rows;
  saveStore(store);
  return rows[index];
}

export function deleteLocalPreset(kind, presetId) {
  const store = loadStore();
  store[kind] = (store[kind] || []).filter((row) => row.id !== presetId);
  saveStore(store);
}

export async function loadReplyPresetOptions() {
  const { items } = listLocalPresets("comments");
  return items.map((row) => ({
    id: row.id,
    label: row.name,
    content: row.content,
  }));
}

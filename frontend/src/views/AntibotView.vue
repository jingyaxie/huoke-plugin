<template>
  <div class="container">
      <div class="panel page-header">
        <div>
          <h2 class="page-title">AntiBot 配置</h2>
          <p class="page-subtitle">
            查看全局反爬策略，并为租户 {{ tenantId }} 设置延迟与行为覆盖
          </p>
        </div>
        <div class="header-actions">
          <el-button :loading="loading" @click="loadAll">刷新</el-button>
        </div>
      </div>

      <el-alert
        v-if="errorMessage"
        :title="errorMessage"
        type="error"
        show-icon
        :closable="false"
        class="status-alert"
      />

      <div class="grid">
        <div class="panel section-panel">
          <h3 class="section-title">全局配置（只读）</h3>
          <p class="section-desc">来自服务端环境变量，所有租户默认继承这些值。</p>
          <el-descriptions v-if="globalConfig" :column="1" border size="small">
            <el-descriptions-item label="随机延迟">
              <StatusTag :value="globalConfig.enabled" />
            </el-descriptions-item>
            <el-descriptions-item label="Stealth 脚本">
              <StatusTag :value="globalConfig.stealth_enabled" />
              <span class="muted-inline">（{{ globalConfig.stealth_version }}）</span>
            </el-descriptions-item>
            <el-descriptions-item label="抓取前校验登录">
              <StatusTag :value="globalConfig.require_login" />
            </el-descriptions-item>
            <el-descriptions-item label="延迟区间">
              {{ formatMs(globalConfig.delay_min_ms) }} ~ {{ formatMs(globalConfig.delay_max_ms) }}
            </el-descriptions-item>
            <el-descriptions-item label="Viewport">
              {{ globalConfig.viewport_width }} × {{ globalConfig.viewport_height }}
            </el-descriptions-item>
            <el-descriptions-item label="Locale / 时区">
              {{ globalConfig.locale }} / {{ globalConfig.timezone }}
            </el-descriptions-item>
            <el-descriptions-item label="User-Agent">
              <span class="ua-text">{{ globalConfig.user_agent }}</span>
            </el-descriptions-item>
          </el-descriptions>
          <el-skeleton v-else :rows="6" animated />
        </div>

        <div class="panel section-panel">
          <div class="section-head">
            <div>
              <h3 class="section-title">租户生效配置</h3>
              <p class="section-desc">
                租户 <code>{{ tenantId }}</code>
                <el-tag v-if="tenantConfig?.has_override" size="small" type="warning" class="tag-gap">已覆盖</el-tag>
                <el-tag v-else size="small" type="info" class="tag-gap">继承全局</el-tag>
              </p>
            </div>
          </div>
          <el-descriptions v-if="effectiveConfig" :column="1" border size="small">
            <el-descriptions-item label="随机延迟">
              <StatusTag :value="effectiveConfig.enabled" />
            </el-descriptions-item>
            <el-descriptions-item label="Stealth 脚本">
              <StatusTag :value="effectiveConfig.stealth_enabled" />
            </el-descriptions-item>
            <el-descriptions-item label="抓取前校验登录">
              <StatusTag :value="effectiveConfig.require_login" />
            </el-descriptions-item>
            <el-descriptions-item label="延迟区间">
              {{ formatMs(effectiveConfig.delay_min_ms) }} ~ {{ formatMs(effectiveConfig.delay_max_ms) }}
            </el-descriptions-item>
          </el-descriptions>
          <p v-if="tenantConfig?.override_path" class="path-hint">覆盖文件：{{ tenantConfig.override_path }}</p>
          <el-skeleton v-else-if="loading" :rows="4" animated />
        </div>
      </div>

      <div class="panel section-panel">
        <h3 class="section-title">租户覆盖编辑</h3>
        <p class="section-desc">
          仅填写需要覆盖的字段；留空或选「继承全局」表示使用全局默认值。保存后写入
          <code>storage/tenants/{tenant_id}/antibot.json</code>。
        </p>

        <el-form label-width="140px" class="override-form">
          <el-form-item label="随机延迟">
            <TriStateSelect v-model="form.enabled" />
          </el-form-item>
          <el-form-item label="Stealth 脚本">
            <TriStateSelect v-model="form.stealth_enabled" />
          </el-form-item>
          <el-form-item label="抓取前校验登录">
            <TriStateSelect v-model="form.require_login" />
          </el-form-item>
          <el-form-item label="延迟下限 (ms)">
            <el-input-number
              v-model="form.delay_min_ms"
              :min="0"
              :max="600000"
              :step="500"
              controls-position="right"
              placeholder="继承全局"
              clearable
            />
          </el-form-item>
          <el-form-item label="延迟上限 (ms)">
            <el-input-number
              v-model="form.delay_max_ms"
              :min="0"
              :max="600000"
              :step="500"
              controls-position="right"
              placeholder="继承全局"
              clearable
            />
          </el-form-item>
          <el-form-item label="延迟倍率">
            <el-input-number
              v-model="form.delay_multiplier"
              :min="0.1"
              :max="10"
              :step="0.1"
              :precision="1"
              controls-position="right"
              placeholder="继承全局 (1.0)"
              clearable
            />
            <span class="field-hint">在 min/max 基础上再整体缩放，例如 1.5 表示更慢、更保守。</span>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="saving" @click="saveOverride">保存覆盖</el-button>
            <el-button :loading="saving" @click="resetOverride">恢复全局默认</el-button>
          </el-form-item>
        </el-form>
      </div>

      <div class="panel section-panel">
        <h3 class="section-title">各场景实际延迟区间</h3>
        <p class="section-desc">基于当前租户生效配置计算（page_load / scroll / between_items 等）。</p>
        <el-table v-if="effectiveConfig?.delay_profiles?.length" :data="effectiveConfig.delay_profiles" stripe>
          <el-table-column prop="name" label="场景" width="160" />
          <el-table-column label="最小延迟">
            <template #default="{ row }">{{ formatMs(row.min_ms) }}</template>
          </el-table-column>
          <el-table-column label="最大延迟">
            <template #default="{ row }">{{ formatMs(row.max_ms) }}</template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="暂无延迟配置" />
      </div>
    </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, onUnmounted, reactive, ref } from "vue";
import { ElMessage, ElOption, ElSelect, ElTag } from "element-plus";
import { getTenantId } from "../api/http";
import {
  deleteTenantAntibotOverride,
  fetchGlobalAntibotConfig,
  fetchTenantAntibotConfig,
  saveTenantAntibotOverride,
} from "../api/antibot";

const StatusTag = defineComponent({
  props: { value: Boolean },
  setup(props) {
    return () =>
      h(ElTag, { type: props.value ? "success" : "info", size: "small" }, () => (props.value ? "开启" : "关闭"));
  },
});

const TriStateSelect = defineComponent({
  props: { modelValue: { type: [Boolean, null], default: null } },
  emits: ["update:modelValue"],
  setup(props, { emit }) {
    const inner = computed({
      get() {
        if (props.modelValue === true) return "true";
        if (props.modelValue === false) return "false";
        return "inherit";
      },
      set(val) {
        if (val === "true") emit("update:modelValue", true);
        else if (val === "false") emit("update:modelValue", false);
        else emit("update:modelValue", null);
      },
    });
    return () =>
      h(
        ElSelect,
        {
          modelValue: inner.value,
          "onUpdate:modelValue": (v) => {
            inner.value = v;
          },
          style: "width: 220px",
        },
        () => [
          h(ElOption, { label: "继承全局", value: "inherit" }),
          h(ElOption, { label: "开启", value: "true" }),
          h(ElOption, { label: "关闭", value: "false" }),
        ]
      );
  },
});

const tenantId = ref(getTenantId());
const loading = ref(false);
const saving = ref(false);
const errorMessage = ref("");
const globalConfig = ref(null);
const tenantConfig = ref(null);

const effectiveConfig = computed(() => tenantConfig.value?.effective || null);

const form = reactive({
  enabled: null,
  stealth_enabled: null,
  require_login: null,
  delay_min_ms: null,
  delay_max_ms: null,
  delay_multiplier: null,
});

function formatMs(value) {
  if (value == null || Number.isNaN(Number(value))) return "-";
  const ms = Number(value);
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s (${Math.round(ms)}ms)`;
  return `${Math.round(ms)}ms`;
}

function applyOverrideToForm(override) {
  form.enabled = override?.enabled ?? null;
  form.stealth_enabled = override?.stealth_enabled ?? null;
  form.require_login = override?.require_login ?? null;
  form.delay_min_ms = override?.delay_min_ms ?? null;
  form.delay_max_ms = override?.delay_max_ms ?? null;
  form.delay_multiplier = override?.delay_multiplier ?? null;
}

function buildPayload() {
  const payload = {};
  if (form.enabled !== null) payload.enabled = form.enabled;
  if (form.stealth_enabled !== null) payload.stealth_enabled = form.stealth_enabled;
  if (form.require_login !== null) payload.require_login = form.require_login;
  if (form.delay_min_ms != null && form.delay_min_ms !== "") payload.delay_min_ms = form.delay_min_ms;
  if (form.delay_max_ms != null && form.delay_max_ms !== "") payload.delay_max_ms = form.delay_max_ms;
  if (form.delay_multiplier != null && form.delay_multiplier !== "") payload.delay_multiplier = form.delay_multiplier;
  return payload;
}

function formatApiError(err, fallback) {
  const detail = err?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join("; ");
  return err?.message || fallback;
}

async function loadAll() {
  loading.value = true;
  errorMessage.value = "";
  tenantId.value = getTenantId();
  try {
    const [globalData, tenantData] = await Promise.all([
      fetchGlobalAntibotConfig(),
      fetchTenantAntibotConfig(tenantId.value),
    ]);
    globalConfig.value = globalData;
    tenantConfig.value = tenantData;
    applyOverrideToForm(tenantData.override);
  } catch (err) {
    errorMessage.value = formatApiError(err, "加载 AntiBot 配置失败");
  } finally {
    loading.value = false;
  }
}

async function saveOverride() {
  const payload = buildPayload();
  if (
    form.delay_min_ms != null &&
    form.delay_max_ms != null &&
    Number(form.delay_max_ms) < Number(form.delay_min_ms)
  ) {
    ElMessage.warning("延迟上限不能小于下限");
    return;
  }
  if (Object.keys(payload).length === 0) {
    ElMessage.warning("请至少填写一项覆盖配置，或使用「恢复全局默认」");
    return;
  }
  saving.value = true;
  try {
    tenantConfig.value = await saveTenantAntibotOverride(payload, tenantId.value);
    applyOverrideToForm(tenantConfig.value.override);
    ElMessage.success("租户 AntiBot 覆盖已保存");
  } catch (err) {
    ElMessage.error(formatApiError(err, "保存失败"));
  } finally {
    saving.value = false;
  }
}

async function resetOverride() {
  saving.value = true;
  try {
    tenantConfig.value = await deleteTenantAntibotOverride(tenantId.value);
    applyOverrideToForm(null);
    ElMessage.success("已恢复为全局默认配置");
  } catch (err) {
    ElMessage.error(formatApiError(err, "恢复失败"));
  } finally {
    saving.value = false;
  }
}

onMounted(() => {
  loadAll();
  window.addEventListener("huoke-tenant-changed", loadAll);
});

onUnmounted(() => {
  window.removeEventListener("huoke-tenant-changed", loadAll);
});
</script>

<style scoped>
.page-header {
  padding: 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.status-alert {
  margin-top: 12px;
}

.grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 12px;
}

.section-panel {
  padding: 16px;
  margin-top: 12px;
}

.section-title {
  margin: 0 0 8px;
  font-size: 16px;
}

.section-desc {
  margin: 0 0 14px;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.5;
}

.section-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.tag-gap {
  margin-left: 8px;
}

.muted-inline {
  margin-left: 8px;
  color: var(--muted);
  font-size: 12px;
}

.ua-text {
  word-break: break-all;
  font-size: 12px;
  color: #374151;
}

.path-hint {
  margin: 12px 0 0;
  font-size: 12px;
  color: var(--muted);
  word-break: break-all;
}

.override-form {
  max-width: 640px;
}

.field-hint {
  display: block;
  margin-top: 6px;
  font-size: 12px;
  color: var(--muted);
}

@media (max-width: 900px) {
  .grid {
    grid-template-columns: 1fr;
  }

  .page-header {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>

<template>
  <section class="settings-section panel">
    <header class="section-head">
      <h2 class="section-title">技能</h2>
      <p class="section-desc">管理租户技能、SkillHub 注册中心与技能效果统计。</p>
    </header>

    <el-collapse v-model="skillHubConfigOpen" style="margin-bottom: 12px">
      <el-collapse-item title="SkillHub 注册中心" name="hub">
        <el-form label-width="100px" size="small">
          <el-form-item label="Registry URL">
            <el-input v-model="skillHubConfig.registry" placeholder="https://skill.xfyun.cn" />
          </el-form-item>
          <el-form-item label="API Token">
            <el-input
              v-model="skillHubTokenInput"
              type="password"
              show-password
              :placeholder="skillHubConfig.token_configured ? '已配置（留空不修改）' : 'sk_...'"
            />
          </el-form-item>
          <el-form-item label="对话自动安装">
            <el-switch v-model="skillHubConfig.auto_install_enabled" />
          </el-form-item>
          <el-button size="small" type="primary" :loading="skillHubConfigSaving" @click="saveSkillHubConfig">
            保存配置
          </el-button>
        </el-form>
        <div class="toolbar-row" style="margin-top: 8px">
          <el-input
            v-model="skillHubSearchQuery"
            size="small"
            placeholder="搜索 SkillHub 技能..."
            style="width: 200px"
            @keyup.enter="doSkillHubSearch"
          />
          <el-button size="small" :loading="skillHubSearching" @click="doSkillHubSearch">搜索</el-button>
          <input ref="skillHubZipInput" type="file" accept=".zip,application/zip" hidden @change="onSkillHubZipSelected" />
          <el-button size="small" @click="skillHubZipInput?.click()">上传 zip 安装</el-button>
        </div>
        <el-table
          v-if="skillHubSearchResults.length"
          :data="skillHubSearchResults"
          size="small"
          stripe
          style="width: 100%; margin-top: 8px"
        >
          <el-table-column prop="slug" label="技能" width="140" />
          <el-table-column prop="namespace" label="空间" width="80" />
          <el-table-column prop="summary" label="描述" min-width="160" show-overflow-tooltip />
          <el-table-column label="操作" width="88">
            <template #default="{ row }">
              <el-button
                link
                type="primary"
                size="small"
                :loading="skillHubInstalling === row.slug"
                @click="installFromHub(row)"
              >
                安装
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-collapse-item>
    </el-collapse>

    <div class="toolbar-row">
      <el-button type="primary" @click="openSkillForm()">新建技能</el-button>
      <el-button @click="openImportDialog">导入</el-button>
      <el-button @click="exportAllSkills">导出 JSON</el-button>
      <el-button @click="loadSkills">刷新</el-button>
    </div>

    <el-table :data="skills" stripe>
      <el-table-column prop="name" label="名称" min-width="120" />
      <el-table-column prop="type" label="类型" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="skillTypeTag(row.type)">{{ skillTypeLabel(row.type) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="scope" label="范围" width="70">
        <template #default="{ row }">
          <span v-if="row.source === 'skillhub'">SkillHub</span>
          <span v-else>{{ row.scope === "global" ? "全局" : "租户" }}</span>
        </template>
      </el-table-column>
      <el-table-column label="包" width="52">
        <template #default="{ row }">
          <el-tag v-if="row.package_path" size="small" type="info">包</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="enabled" label="启用" width="70">
        <template #default="{ row }">
          <el-switch
            v-model="row.enabled"
            size="small"
            :disabled="row.scope === 'global'"
            @change="toggleSkill(row)"
          />
        </template>
      </el-table-column>
      <el-table-column label="评分" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="skillScoreTag(row.effect?.average_score)">
            {{ formatSkillScore(row.effect?.average_score) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="成功率" width="90">
        <template #default="{ row }">
          {{ row.effect?.success_rate != null ? `${row.effect.success_rate}%` : "-" }}
        </template>
      </el-table-column>
      <el-table-column label="拦截风险" width="110">
        <template #default="{ row }">
          <el-tag size="small" :type="riskTagType(row.effect?.risk_level)">
            {{ riskLabel(row.effect?.risk_level, row.effect?.blocked_rate) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="250" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="invokeSkill(row)">调用</el-button>
          <el-button link type="primary" size="small" @click="openSkillEffect(row)">效果</el-button>
          <el-button link type="primary" size="small" @click="exportSkillMd(row)">MD</el-button>
          <el-button
            v-if="row.scope === 'tenant'"
            link
            type="primary"
            size="small"
            @click="openSkillForm(row)"
          >编辑</el-button>
          <el-button
            v-if="row.scope === 'tenant'"
            link
            type="danger"
            size="small"
            @click="removeSkill(row)"
          >删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <p class="skills-hint">
      SkillHub：<code>skillhub:install pdf-parser</code> 或说「安装 xxx 技能」可自动安装；对话中可用
      <code>skillhub_search</code> / <code>skillhub_install</code>。
      回复评论：<code>/reply-comment</code>（需已登录，勿 browser 翻页找评论）
    </p>

    <el-dialog
      v-model="skillEffectVisible"
      :title="`技能效果：${selectedSkillEffect?.skill_id || ''}`"
      width="680px"
    >
      <div v-if="selectedSkillEffect" class="toolbar-row">
        <el-tag size="small">均分 {{ selectedSkillEffect.stats.average_score ?? "-" }}</el-tag>
        <el-tag size="small" type="success">成功 {{ selectedSkillEffect.stats.success ?? 0 }}</el-tag>
        <el-tag size="small" type="danger">失败 {{ selectedSkillEffect.stats.failed ?? 0 }}</el-tag>
        <el-tag size="small" type="info">成功率 {{ selectedSkillEffect.stats.success_rate ?? 0 }}%</el-tag>
        <el-tag size="small" :type="riskTagType(selectedSkillEffect.stats.risk_level)">
          拦截率 {{ selectedSkillEffect.stats.blocked_rate ?? 0 }}%
        </el-tag>
      </div>
      <el-table :data="selectedSkillEffect?.records || []" stripe size="small" style="width: 100%">
        <el-table-column prop="timestamp" label="时间" width="168" />
        <el-table-column prop="status" label="结果" width="88" />
        <el-table-column prop="score" label="评分" width="72" />
        <el-table-column prop="reason" label="原因" min-width="220" show-overflow-tooltip />
        <el-table-column prop="summary" label="摘要" min-width="180" show-overflow-tooltip />
      </el-table>
    </el-dialog>

    <el-dialog v-model="importDialogVisible" title="导入技能" width="640px" destroy-on-close>
      <el-tabs v-model="importTab">
        <el-tab-pane label="SKILL.md" name="markdown">
          <el-input
            v-model="importMarkdown"
            type="textarea"
            :rows="12"
            placeholder="粘贴 SKILL.md 内容，或选择文件..."
          />
          <div class="toolbar-row" style="margin-top: 8px">
            <input ref="mdFileInput" type="file" accept=".md,text/markdown" hidden @change="onMdFileSelected" />
            <el-button size="small" @click="mdFileInput?.click()">选择文件</el-button>
            <el-button size="small" @click="previewMarkdown">预览解析</el-button>
          </div>
          <pre v-if="importPreview" class="import-preview">{{ importPreview }}</pre>
        </el-tab-pane>
        <el-tab-pane label="JSON 包" name="json">
          <input ref="jsonFileInput" type="file" accept=".json,application/json" hidden @change="onJsonFileSelected" />
          <el-button size="small" @click="jsonFileInput?.click()">选择 JSON 文件</el-button>
          <p v-if="importJsonCount" class="hint-text">已加载 {{ importJsonCount }} 个技能</p>
        </el-tab-pane>
      </el-tabs>
      <el-checkbox v-model="importOverwrite" style="margin-top: 12px">覆盖已存在的同名技能</el-checkbox>
      <template #footer>
        <el-button @click="importDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="importLoading" @click="confirmImport">导入</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="skillFormVisible"
      :title="editingSkill ? '编辑技能' : '新建技能'"
      width="640px"
      destroy-on-close
    >
      <el-form label-width="100px">
        <el-form-item label="录入方式">
          <el-radio-group v-model="skillFormMode">
            <el-radio-button value="form">表单</el-radio-button>
            <el-radio-button value="markdown">SKILL.md</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <template v-if="skillFormMode === 'markdown'">
          <el-input
            v-model="skillForm.markdown"
            type="textarea"
            :rows="16"
            placeholder="粘贴 SKILL.md，点击解析预览后保存"
          />
          <div class="toolbar-row" style="margin-top: 8px">
            <el-button size="small" @click="parseSkillFormMarkdown">解析预览</el-button>
          </div>
          <pre v-if="skillForm.markdownPreview" class="import-preview">{{ skillForm.markdownPreview }}</pre>
        </template>
        <template v-else>
          <el-form-item label="技能 ID" required>
            <el-input v-model="skillForm.id" :disabled="!!editingSkill" placeholder="如 my-search-flow" />
          </el-form-item>
          <el-form-item label="名称" required>
            <el-input v-model="skillForm.name" placeholder="显示名称" />
          </el-form-item>
          <el-form-item label="描述" required>
            <el-input v-model="skillForm.description" type="textarea" :rows="2" placeholder="LLM 据此判断何时调用" />
          </el-form-item>
          <el-form-item label="类型">
            <el-select v-model="skillForm.type" style="width: 100%">
              <el-option label="指令型 (instruction)" value="instruction" />
              <el-option label="动作流 (actions)" value="actions" />
              <el-option label="内置能力 (builtin)" value="builtin" />
            </el-select>
          </el-form-item>
          <el-form-item label="仅手动触发">
            <el-switch v-model="skillForm.disable_model_invocation" />
            <span class="hint-text">开启后模型不会自动调用，需 /skill-id 或 invoke_skill</span>
          </el-form-item>
          <el-form-item v-if="skillForm.type === 'builtin'" label="内置处理器">
            <el-select v-model="skillForm.builtin_handler" style="width: 100%">
              <el-option
                v-for="h in builtinHandlers"
                :key="h.id"
                :label="`${h.id} — ${h.description}`"
                :value="h.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item v-if="skillForm.type === 'instruction'" label="指令内容">
            <el-input
              v-model="skillForm.content"
              type="textarea"
              :rows="8"
              placeholder="支持 {{param}} 占位符，激活后注入给智能体执行"
            />
          </el-form-item>
          <el-form-item v-if="skillForm.type === 'actions'" label="动作 JSON">
            <el-input
              v-model="skillForm.actionsJson"
              type="textarea"
              :rows="10"
              placeholder='[{"tool":"browser_goto","args":{"url":"https://..."}}]'
            />
          </el-form-item>
          <el-form-item label="参数 JSON">
            <el-input
              v-model="skillForm.parametersJson"
              type="textarea"
              :rows="4"
              placeholder='[{"name":"keyword","type":"string","description":"关键词","required":true}]'
            />
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="skillFormVisible = false">取消</el-button>
        <el-button type="primary" :loading="skillSaving" @click="saveSkill">
          {{ skillFormMode === "markdown" ? "解析并保存" : "保存" }}
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  createSkill,
  deleteSkill,
  downloadWithAuth,
  exportSkillsJson,
  fetchBuiltinHandlers,
  fetchSkillEffectDetail,
  fetchSkillEffects,
  fetchSkills,
  fetchSkillHubConfig,
  importSkillMarkdown,
  importSkillsJson,
  installSkillHub,
  installSkillHubZip,
  parseSkillMarkdown,
  searchSkillHub,
  skillMarkdownDownloadUrl,
  updateSkill,
  updateSkillHubConfig,
} from "../../api/agent";

const router = useRouter();

function emptySkillForm() {
  return {
    id: "",
    name: "",
    description: "",
    type: "instruction",
    content: "",
    actionsJson: "[]",
    parametersJson: "[]",
    builtin_handler: null,
    disable_model_invocation: false,
    markdown: "",
    markdownPreview: "",
  };
}

function skillTypeLabel(type) {
  return { instruction: "指令", actions: "动作", builtin: "内置" }[type] || type;
}

function skillTypeTag(type) {
  return { instruction: "primary", actions: "success", builtin: "info" }[type] || "";
}

function formatSkillScore(score) {
  if (score == null) return "-";
  return `${Math.round(Number(score))}`;
}

function skillScoreTag(score) {
  const n = Number(score ?? 0);
  if (n >= 85) return "success";
  if (n >= 60) return "warning";
  return "danger";
}

function riskTagType(level) {
  if (level === "high") return "danger";
  if (level === "medium") return "warning";
  return "success";
}

function riskLabel(level, rate) {
  const n = Number(rate ?? 0);
  if (level === "high") return `高(${n}%)`;
  if (level === "medium") return `中(${n}%)`;
  return `低(${n}%)`;
}

const skillHubConfigOpen = ref(["hub"]);
const skillHubConfig = ref({
  registry: "https://skill.xfyun.cn",
  token_configured: false,
  auto_install_enabled: true,
});
const skillHubTokenInput = ref("");
const skillHubConfigSaving = ref(false);
const skillHubSearchQuery = ref("");
const skillHubSearchResults = ref([]);
const skillHubSearching = ref(false);
const skillHubInstalling = ref(null);
const skillHubZipInput = ref(null);
const skills = ref([]);
const skillEffectVisible = ref(false);
const selectedSkillEffect = ref(null);
const skillFormVisible = ref(false);
const skillSaving = ref(false);
const editingSkill = ref(null);
const builtinHandlers = ref([]);
const skillFormMode = ref("form");
const skillForm = ref(emptySkillForm());
const importDialogVisible = ref(false);
const importTab = ref("markdown");
const importMarkdown = ref("");
const importPreview = ref("");
const importJsonSkills = ref([]);
const importJsonCount = ref(0);
const importOverwrite = ref(false);
const importLoading = ref(false);
const mdFileInput = ref(null);
const jsonFileInput = ref(null);

async function loadSkillHubConfig() {
  try {
    skillHubConfig.value = await fetchSkillHubConfig();
  } catch {
    /* ignore */
  }
}

async function saveSkillHubConfig() {
  skillHubConfigSaving.value = true;
  try {
    const payload = {
      registry: skillHubConfig.value.registry,
      auto_install_enabled: skillHubConfig.value.auto_install_enabled,
    };
    if (skillHubTokenInput.value.trim()) {
      payload.token = skillHubTokenInput.value.trim();
    }
    skillHubConfig.value = await updateSkillHubConfig(payload);
    skillHubTokenInput.value = "";
    ElMessage.success("SkillHub 配置已保存");
  } catch (err) {
    ElMessage.error(err.message || "保存失败");
  } finally {
    skillHubConfigSaving.value = false;
  }
}

async function doSkillHubSearch() {
  const q = skillHubSearchQuery.value.trim();
  if (!q) {
    ElMessage.warning("请输入搜索关键词");
    return;
  }
  skillHubSearching.value = true;
  try {
    const data = await searchSkillHub(q, 20);
    skillHubSearchResults.value = data.items || [];
    if (!skillHubSearchResults.value.length) {
      ElMessage.info("未找到匹配技能");
    }
  } catch (err) {
    ElMessage.error(err.message || "搜索失败");
  } finally {
    skillHubSearching.value = false;
  }
}

async function installFromHub(row) {
  const coord =
    row.namespace && row.namespace !== "global"
      ? `@${row.namespace}/${row.slug}`
      : row.slug;
  skillHubInstalling.value = row.slug;
  try {
    await installSkillHub({ coordinate: coord, overwrite: false });
    ElMessage.success(`已安装 ${coord}`);
    await loadSkills();
  } catch (err) {
    ElMessage.error(err.message || "安装失败");
  } finally {
    skillHubInstalling.value = null;
  }
}

async function onSkillHubZipSelected(ev) {
  const file = ev.target?.files?.[0];
  if (!file) return;
  try {
    await installSkillHubZip(file, false);
    ElMessage.success("已从 zip 安装技能");
    await loadSkills();
  } catch (err) {
    ElMessage.error(err.message || "安装失败");
  }
  ev.target.value = "";
}

async function loadSkills() {
  try {
    const data = await fetchSkills();
    const effects = await fetchSkillEffects().catch(() => []);
    const effectMap = new Map((effects || []).map((item) => [item.skill_id, item]));
    skills.value = (data.items || []).map((item) => ({
      ...item,
      effect: effectMap.get(item.id) || null,
    }));
  } catch (err) {
    ElMessage.error(err.message || "加载技能失败");
  }
}

async function openSkillEffect(row) {
  skillEffectVisible.value = true;
  selectedSkillEffect.value = { skill_id: row.id, stats: row.effect || {}, records: [] };
  try {
    const data = await fetchSkillEffectDetail(row.id, 30);
    selectedSkillEffect.value = data;
  } catch (err) {
    ElMessage.error(err.message || "加载技能效果失败");
  }
}

async function loadBuiltinHandlers() {
  try {
    builtinHandlers.value = await fetchBuiltinHandlers();
  } catch {
    builtinHandlers.value = [];
  }
}

function openSkillForm(row = null) {
  editingSkill.value = row;
  skillFormMode.value = "form";
  if (row) {
    skillForm.value = {
      id: row.id,
      name: row.name,
      description: row.description,
      type: row.type,
      content: row.content || "",
      actionsJson: JSON.stringify(row.actions || [], null, 2),
      parametersJson: JSON.stringify(row.parameters || [], null, 2),
      builtin_handler: row.builtin_handler,
      disable_model_invocation: row.disable_model_invocation || false,
      markdown: "",
      markdownPreview: "",
    };
  } else {
    skillForm.value = emptySkillForm();
  }
  skillFormVisible.value = true;
}

async function parseSkillFormMarkdown() {
  if (!skillForm.value.markdown.trim()) {
    ElMessage.warning("请先粘贴 SKILL.md");
    return;
  }
  try {
    const data = await parseSkillMarkdown(skillForm.value.markdown);
    skillForm.value.markdownPreview = JSON.stringify(data.skill, null, 2);
  } catch (err) {
    ElMessage.error(err.message || "解析失败");
  }
}

async function saveSkill() {
  if (skillFormMode.value === "markdown") {
    if (!skillForm.value.markdown.trim()) {
      ElMessage.warning("请粘贴 SKILL.md");
      return;
    }
    skillSaving.value = true;
    try {
      await importSkillMarkdown(skillForm.value.markdown, false);
      ElMessage.success("技能已从 SKILL.md 导入");
      skillFormVisible.value = false;
      await loadSkills();
    } catch (err) {
      ElMessage.error(err.message || "导入失败");
    } finally {
      skillSaving.value = false;
    }
    return;
  }

  let parameters = [];
  let actions = [];
  try {
    parameters = JSON.parse(skillForm.value.parametersJson || "[]");
    if (skillForm.value.type === "actions") {
      actions = JSON.parse(skillForm.value.actionsJson || "[]");
    }
  } catch {
    ElMessage.error("参数或动作 JSON 格式无效");
    return;
  }

  const payload = {
    name: skillForm.value.name.trim(),
    description: skillForm.value.description.trim(),
    type: skillForm.value.type,
    parameters,
    content: skillForm.value.content,
    actions,
    builtin_handler: skillForm.value.type === "builtin" ? skillForm.value.builtin_handler : null,
    disable_model_invocation: skillForm.value.disable_model_invocation,
  };

  skillSaving.value = true;
  try {
    if (editingSkill.value) {
      await updateSkill(editingSkill.value.id, payload);
      ElMessage.success("技能已更新");
    } else {
      await createSkill({ ...payload, id: skillForm.value.id.trim() });
      ElMessage.success("技能已创建");
    }
    skillFormVisible.value = false;
    await loadSkills();
  } catch (err) {
    ElMessage.error(err.message || "保存失败");
  } finally {
    skillSaving.value = false;
  }
}

async function toggleSkill(row) {
  if (row.scope === "global") return;
  try {
    await updateSkill(row.id, { enabled: row.enabled });
  } catch (err) {
    row.enabled = !row.enabled;
    ElMessage.error(err.message || "更新失败");
  }
}

async function removeSkill(row) {
  try {
    await ElMessageBox.confirm(`确定删除技能「${row.name}」？`, "确认");
    await deleteSkill(row.id);
    ElMessage.success("已删除");
    await loadSkills();
  } catch (err) {
    if (err !== "cancel") ElMessage.error(err.message || "删除失败");
  }
}

function invokeSkill(row) {
  router.push({ path: "/agent", query: { invoke: row.id, invokeName: row.name } });
}

function openImportDialog() {
  importTab.value = "markdown";
  importMarkdown.value = "";
  importPreview.value = "";
  importJsonSkills.value = [];
  importJsonCount.value = 0;
  importOverwrite.value = false;
  importDialogVisible.value = true;
}

async function previewMarkdown() {
  if (!importMarkdown.value.trim()) {
    ElMessage.warning("请先粘贴 SKILL.md");
    return;
  }
  try {
    const data = await parseSkillMarkdown(importMarkdown.value);
    importPreview.value = JSON.stringify(data.skill, null, 2);
  } catch (err) {
    ElMessage.error(err.message || "解析失败");
  }
}

async function onMdFileSelected(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  importMarkdown.value = await file.text();
  event.target.value = "";
}

async function onJsonFileSelected(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    const raw = JSON.parse(await file.text());
    const list = raw.skills || raw.items || (Array.isArray(raw) ? raw : []);
    importJsonSkills.value = list;
    importJsonCount.value = list.length;
  } catch {
    ElMessage.error("JSON 格式无效");
  }
  event.target.value = "";
}

async function confirmImport() {
  importLoading.value = true;
  try {
    if (importTab.value === "markdown") {
      await importSkillMarkdown(importMarkdown.value, importOverwrite.value);
      ElMessage.success("SKILL.md 导入成功");
    } else {
      if (!importJsonSkills.value.length) {
        ElMessage.warning("请先选择 JSON 文件");
        return;
      }
      const result = await importSkillsJson(importJsonSkills.value, importOverwrite.value);
      ElMessage.success(`导入 ${result.imported.length} 个，跳过 ${result.skipped.length} 个`);
      if (result.errors?.length) ElMessage.warning(result.errors.join("; "));
    }
    importDialogVisible.value = false;
    await loadSkills();
  } catch (err) {
    ElMessage.error(err.message || "导入失败");
  } finally {
    importLoading.value = false;
  }
}

async function exportAllSkills() {
  try {
    const bundle = await exportSkillsJson();
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "skills-export.json";
    link.click();
    URL.revokeObjectURL(link.href);
  } catch (err) {
    ElMessage.error(err.message || "导出失败");
  }
}

async function exportSkillMd(row) {
  try {
    await downloadWithAuth(skillMarkdownDownloadUrl(row.id), `${row.id}-SKILL.md`);
  } catch (err) {
    ElMessage.error(err.message || "导出失败");
  }
}

onMounted(() => {
  loadSkills();
  loadSkillHubConfig();
  loadBuiltinHandlers();
});
</script>

<style scoped>
.skills-hint {
  margin-top: 12px;
  font-size: 12px;
  color: #888;
}

.import-preview {
  margin-top: 10px;
  padding: 10px;
  background: #f8fafc;
  border-radius: 6px;
  font-size: 11px;
  max-height: 200px;
  overflow: auto;
  white-space: pre-wrap;
}
</style>

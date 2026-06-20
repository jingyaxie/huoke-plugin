<template>
  <section class="settings-section panel">
    <header class="section-head">
      <h2 class="section-title">Agent 档案</h2>
      <p class="section-desc">定义不同角色 Agent 的系统提示、Skill 范围与规则排除项。</p>
    </header>

    <div class="toolbar-row">
      <el-button type="primary" @click="openAgentProfileForm()">新建 Agent</el-button>
      <el-button @click="loadAll">刷新</el-button>
    </div>

    <el-table :data="agentProfiles" stripe>
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column prop="id" label="ID" min-width="140" show-overflow-tooltip />
      <el-table-column prop="scope" label="范围" width="80">
        <template #default="{ row }">{{ row.scope === "global" ? "内置" : "租户" }}</template>
      </el-table-column>
      <el-table-column prop="enabled" label="启用" width="72">
        <template #default="{ row }">{{ row.enabled ? "是" : "否" }}</template>
      </el-table-column>
      <el-table-column label="操作" width="140">
        <template #default="{ row }">
          <el-button v-if="row.scope === 'tenant'" link type="primary" size="small" @click="openAgentProfileForm(row)">
            编辑
          </el-button>
          <el-button v-if="row.scope === 'tenant'" link type="danger" size="small" @click="removeAgentProfile(row)">
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="agentProfileFormVisible" :title="editingAgentProfile ? '编辑 Agent' : '新建 Agent'" width="640px">
      <el-form label-width="110px">
        <el-form-item label="档案 ID" required>
          <el-input v-model="agentProfileForm.id" :disabled="!!editingAgentProfile" placeholder="如 comment-reply-bot" />
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input v-model="agentProfileForm.name" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="agentProfileForm.description" />
        </el-form-item>
        <el-form-item label="运行时内核">
          <el-switch v-model="agentProfileForm.inherit_base_prompt" />
        </el-form-item>
        <el-form-item label="标准获客流程">
          <el-switch v-model="agentProfileForm.inherit_workflow_prompt" />
        </el-form-item>
        <el-form-item label="注入历史经验">
          <el-switch v-model="agentProfileForm.inherit_experience_prompt" />
        </el-form-item>
        <el-form-item label="排除规则 ID">
          <el-input v-model="agentProfileForm.excludeRuleIdsText" placeholder="逗号分隔" />
        </el-form-item>
        <el-form-item label="角色提示词" required>
          <el-input v-model="agentProfileForm.system_prompt" type="textarea" :rows="8" />
        </el-form-item>
        <el-form-item label="限定 Skill">
          <el-select
            v-model="agentProfileForm.skill_ids"
            multiple
            filterable
            collapse-tags
            collapse-tags-tooltip
            placeholder="留空=全部已启用 Skill"
            style="width: 100%"
          >
            <el-option v-for="skill in skills" :key="skill.id" :label="skill.name" :value="skill.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="适用平台">
          <el-input v-model="agentProfileForm.platformsText" placeholder="留空=全部，逗号分隔" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="agentProfileForm.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="agentProfileFormVisible = false">取消</el-button>
        <el-button type="primary" :loading="agentProfileSaving" @click="saveAgentProfile">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  createAgentProfile,
  deleteAgentProfile,
  fetchAgentProfiles,
  fetchSkills,
  updateAgentProfile,
} from "../../api/agent";

function emptyAgentProfileForm() {
  return {
    id: "",
    name: "",
    description: "",
    system_prompt: "",
    inherit_base_prompt: true,
    inherit_workflow_prompt: true,
    inherit_experience_prompt: true,
    excludeRuleIdsText: "",
    skill_ids: [],
    platformsText: "",
    enabled: true,
  };
}

const agentProfiles = ref([]);
const skills = ref([]);
const agentProfileFormVisible = ref(false);
const agentProfileSaving = ref(false);
const editingAgentProfile = ref(null);
const agentProfileForm = ref(emptyAgentProfileForm());

async function loadSkills() {
  try {
    const data = await fetchSkills();
    skills.value = data.items || [];
  } catch {
    skills.value = [];
  }
}

async function loadAgentProfiles() {
  try {
    const data = await fetchAgentProfiles();
    agentProfiles.value = data.items || [];
  } catch (err) {
    ElMessage.error(err.message || "加载 Agent 档案失败");
  }
}

async function loadAll() {
  await Promise.all([loadAgentProfiles(), loadSkills()]);
}

function openAgentProfileForm(row = null) {
  editingAgentProfile.value = row;
  if (row) {
    agentProfileForm.value = {
      id: row.id,
      name: row.name,
      description: row.description || "",
      system_prompt: row.system_prompt || "",
      inherit_base_prompt: row.inherit_base_prompt !== false,
      inherit_workflow_prompt: row.inherit_workflow_prompt !== false,
      inherit_experience_prompt: row.inherit_experience_prompt !== false,
      excludeRuleIdsText: (row.exclude_rule_ids || []).join(","),
      skill_ids: [...(row.skill_ids || [])],
      platformsText: (row.platforms || []).join(","),
      enabled: row.enabled !== false,
    };
  } else {
    agentProfileForm.value = emptyAgentProfileForm();
  }
  agentProfileFormVisible.value = true;
}

async function saveAgentProfile() {
  const platforms = agentProfileForm.value.platformsText
    ? agentProfileForm.value.platformsText.split(",").map((s) => s.trim()).filter(Boolean)
    : [];
  const exclude_rule_ids = agentProfileForm.value.excludeRuleIdsText
    ? agentProfileForm.value.excludeRuleIdsText.split(",").map((s) => s.trim()).filter(Boolean)
    : [];
  const payload = {
    name: agentProfileForm.value.name.trim(),
    description: agentProfileForm.value.description.trim(),
    system_prompt: agentProfileForm.value.system_prompt.trim(),
    inherit_base_prompt: agentProfileForm.value.inherit_base_prompt,
    inherit_workflow_prompt: agentProfileForm.value.inherit_workflow_prompt,
    inherit_experience_prompt: agentProfileForm.value.inherit_experience_prompt,
    exclude_rule_ids,
    skill_ids: agentProfileForm.value.skill_ids,
    platforms,
    enabled: agentProfileForm.value.enabled,
  };
  agentProfileSaving.value = true;
  try {
    if (editingAgentProfile.value) {
      await updateAgentProfile(editingAgentProfile.value.id, payload);
    } else {
      await createAgentProfile({ ...payload, id: agentProfileForm.value.id.trim() });
    }
    ElMessage.success("Agent 档案已保存");
    agentProfileFormVisible.value = false;
    await loadAgentProfiles();
  } catch (err) {
    ElMessage.error(err.message || "保存失败");
  } finally {
    agentProfileSaving.value = false;
  }
}

async function removeAgentProfile(row) {
  try {
    await ElMessageBox.confirm(`确定删除 Agent「${row.name}」？`, "确认");
    await deleteAgentProfile(row.id);
    await loadAgentProfiles();
  } catch (err) {
    if (err !== "cancel") ElMessage.error(err.message || "删除失败");
  }
}

onMounted(loadAll);
</script>

<style scoped>
.form-hint {
  margin-left: 8px;
  font-size: 12px;
  color: var(--muted);
}
</style>

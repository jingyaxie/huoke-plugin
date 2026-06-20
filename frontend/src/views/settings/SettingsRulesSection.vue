<template>
  <section class="settings-section panel">
    <header class="section-head">
      <h2 class="section-title">规则</h2>
      <p class="section-desc">Rules 会在对话中注入系统约束，支持按平台限定范围。</p>
    </header>

    <div class="toolbar-row">
      <el-button type="primary" @click="openRuleForm()">新建规则</el-button>
      <el-button @click="loadRules">刷新</el-button>
    </div>

    <el-table :data="rules" stripe>
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column prop="scope" label="范围" width="80">
        <template #default="{ row }">{{ row.scope === "global" ? "全局" : "租户" }}</template>
      </el-table-column>
      <el-table-column prop="always_apply" label="始终" width="72">
        <template #default="{ row }">{{ row.always_apply ? "是" : "否" }}</template>
      </el-table-column>
      <el-table-column label="操作" width="140">
        <template #default="{ row }">
          <el-button v-if="row.scope === 'tenant'" link type="primary" size="small" @click="openRuleForm(row)">
            编辑
          </el-button>
          <el-button v-if="row.scope === 'tenant'" link type="danger" size="small" @click="removeRule(row)">
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="ruleFormVisible" :title="editingRule ? '编辑规则' : '新建规则'" width="560px">
      <el-form label-width="100px">
        <el-form-item label="规则 ID" required>
          <el-input v-model="ruleForm.id" :disabled="!!editingRule" />
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input v-model="ruleForm.name" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="ruleForm.description" />
        </el-form-item>
        <el-form-item label="始终应用">
          <el-switch v-model="ruleForm.always_apply" />
        </el-form-item>
        <el-form-item label="平台">
          <el-input v-model="ruleForm.platformsText" placeholder="留空=全部，逗号分隔如 douyin,xiaohongshu" />
        </el-form-item>
        <el-form-item label="规则内容" required>
          <el-input v-model="ruleForm.content" type="textarea" :rows="8" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="ruleFormVisible = false">取消</el-button>
        <el-button type="primary" :loading="ruleSaving" @click="saveRule">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { createRule, deleteRule, fetchRules, updateRule } from "../../api/agent";

function emptyRuleForm() {
  return { id: "", name: "", description: "", content: "", always_apply: true, platformsText: "" };
}

const rules = ref([]);
const ruleFormVisible = ref(false);
const ruleSaving = ref(false);
const editingRule = ref(null);
const ruleForm = ref(emptyRuleForm());

async function loadRules() {
  try {
    const data = await fetchRules();
    rules.value = data.items || [];
  } catch (err) {
    ElMessage.error(err.message || "加载规则失败");
  }
}

function openRuleForm(row = null) {
  editingRule.value = row;
  ruleForm.value = row
    ? {
        id: row.id,
        name: row.name,
        description: row.description || "",
        content: row.content,
        always_apply: row.always_apply,
        platformsText: (row.platforms || []).join(","),
      }
    : emptyRuleForm();
  ruleFormVisible.value = true;
}

async function saveRule() {
  const platforms = ruleForm.value.platformsText
    ? ruleForm.value.platformsText.split(",").map((s) => s.trim()).filter(Boolean)
    : [];
  const payload = {
    name: ruleForm.value.name.trim(),
    description: ruleForm.value.description.trim(),
    content: ruleForm.value.content.trim(),
    always_apply: ruleForm.value.always_apply,
    platforms,
  };
  ruleSaving.value = true;
  try {
    if (editingRule.value) {
      await updateRule(editingRule.value.id, payload);
    } else {
      await createRule({ ...payload, id: ruleForm.value.id.trim() });
    }
    ElMessage.success("规则已保存");
    ruleFormVisible.value = false;
    await loadRules();
  } catch (err) {
    ElMessage.error(err.message || "保存失败");
  } finally {
    ruleSaving.value = false;
  }
}

async function removeRule(row) {
  try {
    await ElMessageBox.confirm(`确定删除规则「${row.name}」？`, "确认");
    await deleteRule(row.id);
    await loadRules();
  } catch (err) {
    if (err !== "cancel") ElMessage.error(err.message || "删除失败");
  }
}

onMounted(loadRules);
</script>

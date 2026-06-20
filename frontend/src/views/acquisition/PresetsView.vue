<template>
  <div class="acquisition-page">
    <header class="page-header">
      <div>
        <h1 class="page-title">评论/私信预设</h1>
        <p class="page-subtitle">管理评论回复与私信触达模板，创建任务时可按需勾选。</p>
      </div>
      <el-button type="primary" class="create-btn" @click="openCreate">+ 添加预设</el-button>
    </header>

    <el-alert
      v-if="useLocalPresets"
      type="info"
      :closable="false"
      show-icon
      title="当前使用浏览器本地存储预设（插件模式无需 Python 后端）。"
      class="panel-block"
    />

    <section class="table-card panel page-body">
      <el-table v-loading="loading" :data="rows" stripe empty-text="暂无预设">
        <el-table-column prop="name" label="名称" width="180" />
        <el-table-column prop="kindLabel" label="类型" width="120" />
        <el-table-column prop="content" label="内容" min-width="280" show-overflow-tooltip />
        <el-table-column prop="updated_at" label="更新时间" width="180">
          <template #default="{ row }">{{ formatTime(row.updated_at || row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" size="small" @click="removeRow(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="dialogOpen" :title="editing ? '编辑预设' : '添加预设'" width="520px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="类型" required>
          <el-select v-model="form.kind" :disabled="!!editing" style="width: 100%">
            <el-option label="评论回复" value="comments" />
            <el-option label="私信触达" value="dm-openers" />
          </el-select>
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="预设名称" />
        </el-form-item>
        <el-form-item label="内容" required>
          <el-input v-model="form.content" type="textarea" :rows="5" placeholder="支持 {{nickname}} 等变量" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { createPreset, deletePreset, listPresets, updatePreset } from "../../api/presets";
import {
  createLocalPreset,
  deleteLocalPreset,
  listLocalPresets,
  updateLocalPreset,
} from "../../utils/localPresets";

const loading = ref(false);
const saving = ref(false);
const dialogOpen = ref(false);
const editing = ref(null);
const comments = ref([]);
const dmOpeners = ref([]);
const useLocalPresets = ref(false);

const form = reactive({
  kind: "comments",
  name: "",
  content: "",
});

const rows = computed(() => {
  const commentRows = (comments.value || []).map((row) => ({
    ...row,
    kind: "comments",
    kindLabel: "评论回复",
  }));
  const dmRows = (dmOpeners.value || []).map((row) => ({
    ...row,
    kind: "dm-openers",
    kindLabel: "私信触达",
  }));
  return [...commentRows, ...dmRows].sort((a, b) => {
    const ta = Date.parse(a.updated_at || a.created_at || "") || 0;
    const tb = Date.parse(b.updated_at || b.created_at || "") || 0;
    return tb - ta;
  });
});

function formatTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

async function loadLocal() {
  const commentResp = listLocalPresets("comments");
  const dmResp = listLocalPresets("dm-openers");
  comments.value = commentResp.items || [];
  dmOpeners.value = dmResp.items || [];
  useLocalPresets.value = true;
}

async function load() {
  loading.value = true;
  try {
    const [commentResp, dmResp] = await Promise.all([listPresets("comments"), listPresets("dm-openers")]);
    comments.value = commentResp.items || [];
    dmOpeners.value = dmResp.items || [];
    useLocalPresets.value = false;
  } catch {
    await loadLocal();
  } finally {
    loading.value = false;
  }
}

function openCreate() {
  editing.value = null;
  form.kind = "comments";
  form.name = "";
  form.content = "";
  dialogOpen.value = true;
}

function openEdit(row) {
  editing.value = row;
  form.kind = row.kind;
  form.name = row.name;
  form.content = row.content;
  dialogOpen.value = true;
}

async function save() {
  if (!form.name.trim() || !form.content.trim()) {
    ElMessage.warning("请填写名称和内容");
    return;
  }
  saving.value = true;
  try {
    if (useLocalPresets.value) {
      if (editing.value) {
        updateLocalPreset(editing.value.kind, editing.value.id, {
          name: form.name.trim(),
          content: form.content.trim(),
        });
      } else {
        createLocalPreset(form.kind, {
          name: form.name.trim(),
          content: form.content.trim(),
        });
      }
    } else if (editing.value) {
      await updatePreset(editing.value.kind, editing.value.id, {
        name: form.name.trim(),
        content: form.content.trim(),
      });
    } else {
      await createPreset(form.kind, {
        name: form.name.trim(),
        content: form.content.trim(),
      });
    }
    ElMessage.success(editing.value ? "已更新" : "已创建");
    dialogOpen.value = false;
    await load();
  } catch (err) {
    ElMessage.error(err.message || "保存失败");
  } finally {
    saving.value = false;
  }
}

async function removeRow(row) {
  try {
    await ElMessageBox.confirm(`确认删除预设「${row.name}」？`, "删除预设", { type: "warning" });
    if (useLocalPresets.value) {
      deleteLocalPreset(row.kind, row.id);
    } else {
      await deletePreset(row.kind, row.id);
    }
    ElMessage.success("已删除");
    await load();
  } catch (err) {
    if (err !== "cancel") {
      ElMessage.error(err?.message || "删除失败");
    }
  }
}

onMounted(() => {
  void load();
});
</script>

<style scoped>
.acquisition-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.create-btn {
  flex-shrink: 0;
  padding: 0 20px;
}

.panel-block {
  width: 100%;
}

.page-body {
  padding: 20px;
}
</style>

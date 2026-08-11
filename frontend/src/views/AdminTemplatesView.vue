<template>
  <div class="admin-templates-page">
    <AppNavbar />

    <main class="admin-templates-page__main">
      <div class="admin-templates-page__container">
        <div class="admin-templates-page__header">
          <div>
            <h1 class="admin-templates-page__title">模板管理</h1>
            <p class="admin-templates-page__desc">
              维护 RAG 推荐使用的排版模板；新增/编辑模板会自动向量化，删除需谨慎
            </p>
          </div>
          <el-button type="primary" class="admin-templates-page__new" @click="openCreate">
            <el-icon><Plus /></el-icon>
            新增模板
          </el-button>
        </div>

        <div class="admin-templates-card">
          <el-table v-if="templates.length > 0" :data="templates" style="width: 100%">
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="name" label="模板名称" min-width="160">
              <template #default="{ row }">
                <div class="admin-templates-page__name">
                  {{ row.name }}
                  <el-tag v-if="row.is_system" size="small" type="info" round>内置</el-tag>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="description" label="语义描述" min-width="280" show-overflow-tooltip />
            <el-table-column prop="usage_count" label="使用次数" width="100" align="right" />
            <el-table-column label="操作" width="160" fixed="right">
              <template #default="{ row }">
                <el-button text type="primary" @click="openEdit(row)">编辑</el-button>
                <el-button
                  text
                  type="danger"
                  :disabled="row.is_system"
                  @click="handleDelete(row)"
                >
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>

          <EmptyState
            v-else
            title="暂无模板"
            description="点击右上角「新增模板」创建第一个排版模板"
          />
        </div>

        <p class="admin-templates-page__tip">
          提示：系统内置模板不可删除；模板描述将被 BGE-M3 向量化，用于「AI 推荐模板」匹配。
        </p>
      </div>
    </main>

    <AppFooter />

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑模板' : '新增模板'"
      width="560px"
      destroy-on-close
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <el-form-item label="模板名称" prop="name">
          <el-input v-model="form.name" placeholder="例如：商务标书（投标文件）" maxlength="50" />
        </el-form-item>
        <el-form-item label="语义描述" prop="description">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="4"
            resize="none"
            placeholder="描述该模板适合的文档类型/行业，例如：工程类投标文件，正文仿宋GB2312 三号，标题黑体二号"
            maxlength="2000"
          />
        </el-form-item>
        <el-form-item label="样式配置（JSON，可选）">
          <el-input
            v-model="configText"
            type="textarea"
            :rows="6"
            resize="none"
            placeholder='例如：{"paragraph_styles": {"font": "宋体", "font_size_pt": 12}}'
          />
          <span v-if="configError" class="admin-templates-page__config-error">{{ configError }}</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">
          {{ editingId ? '保存修改' : '创建并向量化' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import AppNavbar from '@/components/AppNavbar.vue'
import AppFooter from '@/components/AppFooter.vue'
import EmptyState from '@/components/EmptyState.vue'
import {
  getTemplates,
  createTemplate,
  updateTemplate,
  deleteTemplate,
} from '@/api/templates.js'

const loading = ref(false)
const templates = ref([])

const dialogVisible = ref(false)
const editingId = ref(null)
const submitting = ref(false)
const formRef = ref(null)
const form = reactive({ name: '', description: '' })
const configText = ref('')
const configError = ref('')

const rules = {
  name: [{ required: true, message: '请填写模板名称', trigger: 'blur' }],
  description: [{ required: true, message: '请填写语义描述', trigger: 'blur' }],
}

async function loadTemplates() {
  loading.value = true
  try {
    const data = await getTemplates()
    templates.value = data.templates || []
  } catch (err) {
    ElMessage.error(err.message || '模板加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(loadTemplates)

function openCreate() {
  editingId.value = null
  form.name = ''
  form.description = ''
  configText.value = ''
  configError.value = ''
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  form.name = row.name
  form.description = row.description
  configText.value = row.config ? JSON.stringify(row.config, null, 2) : ''
  configError.value = ''
  dialogVisible.value = true
}

function parseConfig() {
  if (!configText.value.trim()) return {}
  try {
    return JSON.parse(configText.value)
  } catch {
    configError.value = 'JSON 格式不正确，请检查后重试'
    return null
  }
}

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  const config = parseConfig()
  if (config === null) return
  configError.value = ''

  submitting.value = true
  try {
    if (editingId.value) {
      await updateTemplate(editingId.value, {
        name: form.name.trim(),
        description: form.description.trim(),
        config,
      })
      ElMessage.success('模板更新成功')
    } else {
      await createTemplate({
        name: form.name.trim(),
        description: form.description.trim(),
        config,
      })
      ElMessage.success('模板创建成功')
    }
    dialogVisible.value = false
    loadTemplates()
  } catch (err) {
    ElMessage.error(err.message || '保存失败')
  } finally {
    submitting.value = false
  }
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除模板「${row.name}」吗？删除后 AI 推荐将不再命中该模板。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await deleteTemplate(row.id)
    ElMessage.success('模板已删除')
    loadTemplates()
  } catch (err) {
    ElMessage.error(err.message || '删除失败')
  }
}
</script>

<style scoped>
.admin-templates-page__main {
  min-height: calc(100vh - 200px);
  padding: 120px 24px 80px;
  background: transparent;
}

.admin-templates-page__container {
  max-width: 1000px;
  margin: 0 auto;
}

.admin-templates-page__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
}

.admin-templates-page__title {
  font-size: 32px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.admin-templates-page__desc {
  font-size: 15px;
  color: var(--text-secondary);
  margin: 0;
}

.admin-templates-page__new {
  border-radius: 999px;
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  border: none;
  box-shadow: 0 8px 20px rgba(79, 70, 229, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.30);
}

.admin-templates-card {
  background: var(--glass-surface);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
  overflow: hidden;
}

.admin-templates-page__name {
  display: flex;
  align-items: center;
  gap: 8px;
}

.admin-templates-page__tip {
  font-size: 12px;
  color: var(--text-tertiary);
  margin: 16px 0 0;
}

.admin-templates-page__config-error {
  display: block;
  margin-top: 6px;
  font-size: 12px;
  color: var(--danger-color, #dc2626);
}
</style>

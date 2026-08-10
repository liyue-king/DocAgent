<template>
  <div class="knowledge-page">
    <AppNavbar />

    <main class="knowledge-page__main">
      <div class="knowledge-page__container">
        <div class="knowledge-page__header">
          <div>
            <h1 class="knowledge-page__title">我的知识库</h1>
            <p class="knowledge-page__desc">
              上传你的专属文档，AI 助手回答时会优先参考你自己的知识库，每个账号相互独立
            </p>
          </div>
          <div v-if="stats" class="knowledge-page__stat">
            <span class="knowledge-page__stat-num">{{ stats.total_docs }}</span>
            <span class="knowledge-page__stat-label">篇文档 · {{ stats.total_chunks }} 个片段</span>
          </div>
        </div>

        <div v-if="isAdmin" class="knowledge-page__admin-banner">
          <el-icon><Lock /></el-icon>
          <span>你是管理员，还可以维护<b>平台知识库</b>（全体用户共享的 RAG 知识）</span>
          <router-link to="/admin/knowledge">进入平台知识库 →</router-link>
        </div>

        <div class="knowledge-grid">
          <div class="knowledge-card">
            <h2 class="knowledge-card__title">上传我的文档</h2>
            <p class="knowledge-card__desc">
              支持 .docx / .txt / .md，或直接粘贴文本；文档会自动切块并向量化，只对你的账号可见
            </p>

            <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
              <el-form-item label="文档标题" prop="title">
                <el-input v-model="form.title" placeholder="例如：我的论文排版要求" maxlength="50" />
              </el-form-item>

              <el-form-item label="分类（可选）">
                <el-select
                  v-model="form.category"
                  filterable
                  allow-create
                  default-first-option
                  placeholder="选择或输入分类"
                  style="width: 100%"
                >
                  <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
                </el-select>
              </el-form-item>

              <el-form-item label="文档内容">
                <div
                  class="knowledge-card__drop"
                  :class="{ 'knowledge-card__drop--over': isDragOver }"
                  @dragenter.prevent="isDragOver = true"
                  @dragover.prevent="isDragOver = true"
                  @dragleave.prevent="isDragOver = false"
                  @drop.prevent="handleDrop"
                  @click="triggerFile"
                >
                  <input
                    ref="fileInput"
                    type="file"
                    accept=".docx,.txt,.md,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    class="knowledge-card__file-input"
                    @change="handleFileChange"
                  />
                  <template v-if="!selectedFile">
                    <el-icon :size="30"><UploadFilled /></el-icon>
                    <span class="knowledge-card__drop-text">点击或拖拽上传文档</span>
                    <span class="knowledge-card__drop-sub">.docx / .txt / .md，最大 5MB</span>
                  </template>
                  <template v-else>
                    <el-icon :size="22"><Document /></el-icon>
                    <span class="knowledge-card__drop-text">{{ selectedFile.name }}</span>
                    <el-button text type="danger" size="small" @click.stop="clearFile">移除</el-button>
                  </template>
                </div>
                <el-input
                  v-model="form.content"
                  type="textarea"
                  :rows="4"
                  resize="none"
                  placeholder="或直接粘贴文档内容（上传文件后此项可留空）"
                />
              </el-form-item>

              <el-button
                type="primary"
                class="knowledge-card__submit"
                :loading="submitting"
                :disabled="!canSubmit"
                @click="handleSubmit"
              >
                加入我的知识库
              </el-button>
            </el-form>
          </div>

          <div class="knowledge-card knowledge-card--tip">
            <h2 class="knowledge-card__title">文档约定</h2>
            <ul class="knowledge-card__tips">
              <li><b>格式</b>：.docx / .txt / .md，单文件不超过 5MB</li>
              <li><b>内容</b>：上传与你的文档排版、行业规范相关的资料，AI 回答时优先引用</li>
              <li><b>切块</b>：文档按段落自动切块（每块约 600 字），原文同时备份到对象存储</li>
              <li><b>独立</b>：每个人的知识库相互隔离，别人看不到你的文档</li>
              <li><b>生效</b>：上传完成后即可在「AI 助手」中提问，回答会参考你的知识库</li>
            </ul>
            <div class="knowledge-card__tip-cta">
              <el-icon><ChatDotRound /></el-icon>
              <router-link to="/chat">去问 AI 助手</router-link>
            </div>
          </div>
        </div>

        <div class="knowledge-card knowledge-card--list">
          <div class="knowledge-card__list-head">
            <h2 class="knowledge-card__title">我的文档（{{ docs.length }}）</h2>
          </div>

          <div v-if="docs.length" class="knowledge-list">
            <div v-for="doc in docs" :key="doc.doc_id" class="knowledge-list__item">
              <div class="knowledge-list__icon">
                <el-icon><Document /></el-icon>
              </div>
              <div class="knowledge-list__info">
                <div class="knowledge-list__title">{{ doc.title }}</div>
                <div class="knowledge-list__meta">
                  {{ doc.category || '未分类' }} · {{ doc.chunk_count }} 个片段 ·
                  {{ formatDate(doc.created_at) }}
                </div>
              </div>
              <el-button type="danger" text :loading="deletingId === doc.doc_id" @click="handleDelete(doc)">
                删除
              </el-button>
            </div>
          </div>

          <EmptyState
            v-else
            title="知识库还是空的"
            description="上传你的第一份文档，AI 助手就能结合它来回答你的问题"
          />
        </div>
      </div>
    </main>

    <AppFooter />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ChatDotRound, Document, Lock, UploadFilled } from '@element-plus/icons-vue'
import AppNavbar from '@/components/AppNavbar.vue'
import AppFooter from '@/components/AppFooter.vue'
import EmptyState from '@/components/EmptyState.vue'
import { useAuthStore } from '@/stores/auth.js'
import {
  deleteKnowledgeDoc,
  getKnowledgeStats,
  listKnowledgeDocs,
  uploadKnowledge,
} from '@/api/chat.js'

const { isAdmin } = useAuthStore()

const formRef = ref(null)
const fileInput = ref(null)
const selectedFile = ref(null)
const isDragOver = ref(false)
const submitting = ref(false)
const deletingId = ref(null)
const stats = ref(null)
const docs = ref([])

const categories = [
  '教育', '商务', '政府', '工程', '个人', '金融', '医疗', '法律', '餐饮', '制造', '其他',
]

const form = reactive({
  title: '',
  category: '',
  content: '',
})

const rules = {
  title: [{ required: true, message: '请填写文档标题', trigger: 'blur' }],
}

const canSubmit = computed(() => form.title.trim() && (selectedFile.value || form.content.trim()))

async function loadAll() {
  await Promise.allSettled([loadStats(), loadDocs()])
}

async function loadStats() {
  try {
    const data = await getKnowledgeStats()
    stats.value = data
  } catch {
    stats.value = null
  }
}

async function loadDocs() {
  try {
    const data = await listKnowledgeDocs()
    docs.value = data.docs || []
  } catch (err) {
    ElMessage.error(err.message || '加载文档列表失败')
  }
}

onMounted(loadAll)

function triggerFile() {
  fileInput.value?.click()
}

function handleFileChange(e) {
  const file = e.target.files?.[0]
  if (file) setFile(file)
}

function handleDrop(e) {
  isDragOver.value = false
  const file = e.dataTransfer.files?.[0]
  if (file) setFile(file)
}

function setFile(file) {
  const okExt = /\.(docx|txt|md)$/i
  if (!okExt.test(file.name)) {
    ElMessage.error('仅支持 .docx / .txt / .md 格式')
    return
  }
  if (file.size > 5 * 1024 * 1024) {
    ElMessage.error('文件不能超过 5MB')
    return
  }
  selectedFile.value = file
}

function clearFile() {
  selectedFile.value = null
  if (fileInput.value) fileInput.value.value = ''
}

function formatDate(value) {
  if (!value) return ''
  const d = new Date(value)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    const formData = new FormData()
    formData.append('title', form.title.trim())
    if (form.category.trim()) formData.append('category', form.category.trim())
    if (selectedFile.value) {
      formData.append('file', selectedFile.value)
    } else {
      formData.append('content', form.content.trim())
    }
    const data = await uploadKnowledge(formData)
    ElMessage.success(`已加入我的知识库（${data.chunks} 个片段）`)
    form.title = ''
    form.content = ''
    clearFile()
    loadAll()
  } catch (err) {
    ElMessage.error(err.message || '上传失败')
  } finally {
    submitting.value = false
  }
}

async function handleDelete(doc) {
  try {
    await ElMessageBox.confirm(
      `确定删除「${doc.title}」吗？删除后 AI 助手将不再引用它的内容。`,
      '删除文档',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  deletingId.value = doc.doc_id
  try {
    const data = await deleteKnowledgeDoc(doc.doc_id)
    ElMessage.success(data.msg || '文档已删除')
    loadAll()
  } catch (err) {
    ElMessage.error(err.message || '删除失败')
  } finally {
    deletingId.value = null
  }
}
</script>

<style scoped>
.knowledge-page__main {
  min-height: calc(100vh - 200px);
  padding: 120px 24px 80px;
  background: transparent;
}

.knowledge-page__container {
  max-width: 1000px;
  margin: 0 auto;
}

.knowledge-page__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.knowledge-page__title {
  font-size: 32px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.knowledge-page__desc {
  font-size: 15px;
  color: var(--text-secondary);
  margin: 0;
}

.knowledge-page__stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px 22px;
  background: var(--glass-surface);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
}

.knowledge-page__stat-num {
  font-size: 26px;
  font-weight: 800;
  color: var(--brand-600);
}

.knowledge-page__stat-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.knowledge-page__admin-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  margin-bottom: 24px;
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.14), rgba(255, 255, 255, 0.30));
  border: 1px solid rgba(245, 158, 11, 0.35);
  border-radius: var(--radius-lg);
  font-size: 14px;
  color: var(--text-primary);
}

.knowledge-page__admin-banner a {
  margin-left: auto;
  color: var(--brand-600);
  font-weight: 600;
  text-decoration: none;
}

.knowledge-page__admin-banner a:hover {
  text-decoration: underline;
}

.knowledge-grid {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 24px;
  align-items: start;
}

.knowledge-card {
  background: var(--glass-surface);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-xl);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
  padding: 28px;
}

.knowledge-card--list {
  margin-top: 24px;
}

.knowledge-card__list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.knowledge-card__title {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 6px;
}

.knowledge-card__desc {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0 0 20px;
}

.knowledge-card :deep(.el-form-item__label) {
  color: var(--text-primary);
  font-weight: 600;
}

.knowledge-card :deep(.el-input__inner),
.knowledge-card :deep(.el-textarea__inner) {
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.26);
}

.knowledge-card__drop {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 26px 16px;
  margin-bottom: 12px;
  border: 2px dashed rgba(255, 255, 255, 0.55);
  border-radius: var(--radius-lg);
  cursor: pointer;
  color: var(--brand-600);
  background: rgba(255, 255, 255, 0.10);
  transition: border-color var(--transition-base), background var(--transition-base);
  text-align: center;
}

.knowledge-card__drop:hover,
.knowledge-card__drop--over {
  border-color: var(--brand-500);
  background: rgba(99, 102, 241, 0.14);
}

.knowledge-card__file-input {
  display: none;
}

.knowledge-card__drop-text {
  font-size: 14px;
  color: var(--text-primary);
}

.knowledge-card__drop-sub {
  font-size: 12px;
  color: var(--text-tertiary);
}

.knowledge-card__submit {
  width: 100%;
  height: 44px;
  margin-top: 8px;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  border: none;
  font-size: 15px;
  font-weight: 600;
}

.knowledge-card--tip {
  background: linear-gradient(160deg, rgba(99, 102, 241, 0.12), rgba(255, 255, 255, 0.30) 60%, rgba(255, 255, 255, 0.38));
}

.knowledge-card__tips {
  list-style: none;
  padding: 0;
  margin: 0 0 20px;
}

.knowledge-card__tips li {
  position: relative;
  padding: 8px 0 8px 20px;
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-secondary);
  border-bottom: 1px solid rgba(148, 163, 184, 0.16);
}

.knowledge-card__tips li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 15px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
}

.knowledge-card__tip-cta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--brand-600);
}

.knowledge-card__tip-cta a {
  color: var(--brand-600);
  text-decoration: none;
}

.knowledge-card__tip-cta a:hover {
  text-decoration: underline;
}

.knowledge-list__item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 0;
  border-bottom: 1px solid rgba(148, 163, 184, 0.16);
}

.knowledge-list__item:last-child {
  border-bottom: none;
}

.knowledge-list__icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: rgba(99, 102, 241, 0.12);
  border: 1px solid rgba(99, 102, 241, 0.22);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--brand-600);
  flex-shrink: 0;
}

.knowledge-list__info {
  flex: 1;
  min-width: 0;
}

.knowledge-list__title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.knowledge-list__meta {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 3px;
}

@media (max-width: 900px) {
  .knowledge-grid {
    grid-template-columns: 1fr;
  }
}
</style>

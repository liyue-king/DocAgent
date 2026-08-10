<template>
  <div class="admin-knowledge-page">
    <AppNavbar />

    <main class="admin-knowledge-page__main">
      <div class="admin-knowledge-page__container">
        <div class="admin-knowledge-page__header">
          <div>
            <h1 class="admin-knowledge-page__title">平台知识库</h1>
            <p class="admin-knowledge-page__desc">
              仅管理员可维护，全体用户共享的 RAG 知识；上传行业模板指南文档，让 AI 助手更懂行业
            </p>
          </div>
          <div v-if="stats" class="admin-knowledge-page__stat">
            <span class="admin-knowledge-page__stat-num">{{ stats.total_chunks }}</span>
            <span class="admin-knowledge-page__stat-label">知识片段</span>
          </div>
        </div>

        <div v-if="stats?.categories && Object.keys(stats.categories).length" class="admin-knowledge-page__cats">
          <span
            v-for="(count, cat) in stats.categories"
            :key="cat"
            class="admin-knowledge-page__cat"
          >
            {{ cat }} · {{ count }}
          </span>
        </div>

        <div class="admin-knowledge-grid">
          <div class="admin-knowledge-card">
            <h2 class="admin-knowledge-card__title">上传行业文档</h2>
            <p class="admin-knowledge-card__desc">
              支持 .docx / .txt / .md，或直接粘贴文本；文档会自动切块并向量化入库
            </p>

            <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
              <el-form-item label="文档标题" prop="title">
                <el-input v-model="form.title" placeholder="例如：餐饮行业模板指南" maxlength="50" />
              </el-form-item>

              <el-form-item label="行业分类" prop="category">
                <el-select
                  v-model="form.category"
                  filterable
                  allow-create
                  default-first-option
                  placeholder="选择或输入行业"
                  style="width: 100%"
                >
                  <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
                </el-select>
              </el-form-item>

              <el-form-item label="关联模板（可选）">
                <el-input
                  v-model="form.templateName"
                  placeholder="例如：商务标书（投标文件）"
                  maxlength="50"
                />
              </el-form-item>

              <el-form-item label="文档内容">
                <div
                  class="admin-knowledge-card__drop"
                  :class="{ 'admin-knowledge-card__drop--over': isDragOver }"
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
                    class="admin-knowledge-card__file-input"
                    @change="handleFileChange"
                  />
                  <template v-if="!selectedFile">
                    <el-icon :size="30"><UploadFilled /></el-icon>
                    <span class="admin-knowledge-card__drop-text">点击或拖拽上传文档</span>
                    <span class="admin-knowledge-card__drop-sub">.docx / .txt / .md，最大 5MB</span>
                  </template>
                  <template v-else>
                    <el-icon :size="22"><Document /></el-icon>
                    <span class="admin-knowledge-card__drop-text">{{ selectedFile.name }}</span>
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
                class="admin-knowledge-card__submit"
                :loading="submitting"
                :disabled="!canSubmit"
                @click="handleSubmit"
              >
                向量化入库
              </el-button>
            </el-form>
          </div>

          <div class="admin-knowledge-card admin-knowledge-card--tip">
            <h2 class="admin-knowledge-card__title">使用说明</h2>
            <ul class="admin-knowledge-card__tips">
              <li>先判断行业的典型文档类型，再上传对应的模板指南</li>
              <li>文档按段落自动切块（每块约 600 字），原文同步备份到对象存储</li>
              <li>上传后，AI 助手回答「哪个行业用哪个模板」时优先参考这些知识</li>
              <li>普通用户的知识库相互独立，与本平台知识库互不影响</li>
            </ul>
            <div class="admin-knowledge-card__tip-cta">
              <el-icon><Collection /></el-icon>
              <router-link to="/knowledge">返回我的知识库</router-link>
            </div>
          </div>
        </div>
      </div>
    </main>

    <AppFooter />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Collection, Document, UploadFilled } from '@element-plus/icons-vue'
import AppNavbar from '@/components/AppNavbar.vue'
import AppFooter from '@/components/AppFooter.vue'
import { getAdminKnowledgeStats, uploadAdminKnowledge } from '@/api/chat.js'

const formRef = ref(null)
const fileInput = ref(null)
const selectedFile = ref(null)
const isDragOver = ref(false)
const submitting = ref(false)
const stats = ref(null)

const categories = [
  '教育', '商务', '政府', '工程', '个人', '金融', '医疗', '法律', '餐饮', '制造', '其他',
]

const form = reactive({
  title: '',
  category: '',
  templateName: '',
  content: '',
})

const rules = {
  title: [{ required: true, message: '请填写文档标题', trigger: 'blur' }],
  category: [{ required: true, message: '请选择行业分类', trigger: 'change' }],
}

const canSubmit = computed(() => form.title.trim() && form.category && (selectedFile.value || form.content.trim()))

async function loadStats() {
  try {
    const data = await getAdminKnowledgeStats()
    stats.value = data
  } catch {
    stats.value = null
  }
}

onMounted(loadStats)

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

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    const formData = new FormData()
    formData.append('title', form.title.trim())
    formData.append('category', form.category)
    if (form.templateName.trim()) formData.append('template_name', form.templateName.trim())
    if (selectedFile.value) {
      formData.append('file', selectedFile.value)
    } else {
      formData.append('content', form.content.trim())
    }
    const data = await uploadAdminKnowledge(formData)
    ElMessage.success(`已入库 ${data.chunks} 个知识片段`)
    form.title = ''
    form.templateName = ''
    form.content = ''
    clearFile()
    loadStats()
  } catch (err) {
    ElMessage.error(err.message || '上传失败')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.admin-knowledge-page__main {
  min-height: calc(100vh - 200px);
  padding: 120px 24px 80px;
  background: transparent;
}

.admin-knowledge-page__container {
  max-width: 1000px;
  margin: 0 auto;
}

.admin-knowledge-page__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.admin-knowledge-page__title {
  font-size: 32px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.admin-knowledge-page__desc {
  font-size: 15px;
  color: var(--text-secondary);
  margin: 0;
}

.admin-knowledge-page__stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px 22px;
  background: var(--glass-surface);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
}

.admin-knowledge-page__stat-num {
  font-size: 26px;
  font-weight: 800;
  color: var(--brand-600);
}

.admin-knowledge-page__stat-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.admin-knowledge-page__cats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 24px;
}

.admin-knowledge-page__cat {
  padding: 5px 12px;
  background: rgba(99, 102, 241, 0.10);
  border: 1px solid rgba(99, 102, 241, 0.22);
  border-radius: 9999px;
  font-size: 12px;
  color: var(--brand-600);
}

.admin-knowledge-grid {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 24px;
  align-items: start;
}

.admin-knowledge-card {
  background: var(--glass-surface);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-xl);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
  padding: 28px;
}

.admin-knowledge-card__title {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 6px;
}

.admin-knowledge-card__desc {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0 0 20px;
}

.admin-knowledge-card :deep(.el-form-item__label) {
  color: var(--text-primary);
  font-weight: 600;
}

.admin-knowledge-card :deep(.el-input__inner),
.admin-knowledge-card :deep(.el-textarea__inner) {
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.26);
}

.admin-knowledge-card__drop {
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

.admin-knowledge-card__drop:hover,
.admin-knowledge-card__drop--over {
  border-color: var(--brand-500);
  background: rgba(99, 102, 241, 0.14);
}

.admin-knowledge-card__file-input {
  display: none;
}

.admin-knowledge-card__drop-text {
  font-size: 14px;
  color: var(--text-primary);
}

.admin-knowledge-card__drop-sub {
  font-size: 12px;
  color: var(--text-tertiary);
}

.admin-knowledge-card__submit {
  width: 100%;
  height: 44px;
  margin-top: 8px;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  border: none;
  font-size: 15px;
  font-weight: 600;
}

.admin-knowledge-card--tip {
  background: linear-gradient(160deg, rgba(99, 102, 241, 0.12), rgba(255, 255, 255, 0.30) 60%, rgba(255, 255, 255, 0.38));
}

.admin-knowledge-card__tips {
  list-style: none;
  padding: 0;
  margin: 0 0 20px;
}

.admin-knowledge-card__tips li {
  position: relative;
  padding: 8px 0 8px 20px;
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-secondary);
  border-bottom: 1px solid rgba(148, 163, 184, 0.16);
}

.admin-knowledge-card__tips li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 15px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
}

.admin-knowledge-card__tip-cta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--brand-600);
}

.admin-knowledge-card__tip-cta a {
  color: var(--brand-600);
  text-decoration: none;
}

.admin-knowledge-card__tip-cta a:hover {
  text-decoration: underline;
}

@media (max-width: 900px) {
  .admin-knowledge-grid {
    grid-template-columns: 1fr;
  }
}
</style>

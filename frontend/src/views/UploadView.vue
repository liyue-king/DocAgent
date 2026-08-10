<template>
  <div class="upload-page">
    <AppNavbar />

    <main class="upload-page__main">
      <div class="upload-page__container">
        <div class="upload-page__header">
          <h1 class="upload-page__title">上传文档，开始排版</h1>
          <p class="upload-page__desc">支持 .docx 格式，最大 20MB</p>
        </div>

        <!-- 上传卡片 -->
        <div class="upload-card">
          <div
            class="upload-zone"
            :class="{ 'upload-zone--dragover': isDragOver }"
            @dragenter.prevent="isDragOver = true"
            @dragover.prevent="isDragOver = true"
            @dragleave.prevent="isDragOver = false"
            @drop.prevent="handleDrop"
            @click="triggerFileInput"
          >
            <input
              ref="fileInput"
              type="file"
              accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              class="upload-zone__input"
              @change="handleFileChange"
            />
            <div v-if="!selectedFile" class="upload-zone__placeholder">
              <div class="upload-zone__icon">
                <el-icon :size="48"><Upload /></el-icon>
              </div>
              <h3 class="upload-zone__title">拖拽 Word 文档到此处</h3>
              <p class="upload-zone__desc">或点击上传，仅支持 .docx</p>
            </div>
            <div v-else class="upload-zone__file">
              <div class="upload-zone__file-icon">
                <el-icon :size="32"><Document /></el-icon>
              </div>
              <div class="upload-zone__file-info">
                <span class="upload-zone__file-name">{{ selectedFile.name }}</span>
                <span class="upload-zone__file-size">{{ formatFileSize(selectedFile.size) }}</span>
              </div>
              <el-button circle @click.stop="clearFile">
                <el-icon><Close /></el-icon>
              </el-button>
            </div>
          </div>
        </div>

        <!-- Prompt 输入 -->
        <div class="prompt-card">
          <label class="prompt-card__label">你想怎么排版？</label>
          <el-input
            v-model="prompt"
            type="textarea"
            :rows="4"
            placeholder="例如：把这篇论文按本科毕业论文格式排版，标题黑体三号，正文宋体小四，1.5倍行距"
            resize="none"
          />
          <div class="prompt-card__tags">
            <span class="prompt-card__tags-label">快捷需求：</span>
            <button
              v-for="tag in quickTags"
              :key="tag.label"
              class="prompt-card__tag"
              @click="applyTag(tag)"
            >
              {{ tag.label }}
            </button>
          </div>
        </div>

        <!-- 提交 -->
        <div class="upload-page__actions">
          <el-button
            type="primary"
            size="large"
            class="upload-page__submit"
            :disabled="!canSubmit"
            :loading="submitting"
            @click="handleSubmit"
          >
            开始智能排版
          </el-button>
        </div>

        <!-- 安全提示 -->
        <p class="upload-page__security">
          <el-icon><Lock /></el-icon>
          文件将在 24 小时后自动删除，原文件始终安全备份
        </p>
      </div>
    </main>

    <AppFooter />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Upload, Document, Close, Lock } from '@element-plus/icons-vue'
import AppNavbar from '@/components/AppNavbar.vue'
import AppFooter from '@/components/AppFooter.vue'
import { processDocument } from '@/api/tasks.js'

const router = useRouter()
const route = useRoute()

const fileInput = ref(null)
const selectedFile = ref(null)
const prompt = ref('')
const isDragOver = ref(false)
const submitting = ref(false)

const quickTags = [
  { label: '学术论文', text: '按本科毕业论文格式排版，标题黑体三号，正文宋体小四，1.5倍行距' },
  { label: '商务报告', text: '按商务报告格式排版，标题黑体二号，正文宋体四号，1.5倍行距，段前段后12磅' },
  { label: '政府公文', text: '按政府公文格式排版，标题方正小标宋简体二号，正文仿宋_GB2312三号，行距28磅' },
  { label: '简历', text: '将内容整理成简洁专业的简历格式，统一字体和间距' },
]

onMounted(() => {
  const tpl = route.query.template
  if (tpl) {
    prompt.value = `请按「${tpl}」模板进行排版`
  }
})

const canSubmit = computed(() => selectedFile.value && prompt.value.trim())

function triggerFileInput() {
  fileInput.value?.click()
}

function handleFileChange(e) {
  const file = e.target.files?.[0]
  if (file) validateAndSetFile(file)
}

function handleDrop(e) {
  isDragOver.value = false
  const file = e.dataTransfer.files?.[0]
  if (file) validateAndSetFile(file)
}

function validateAndSetFile(file) {
  if (!file.name.endsWith('.docx')) {
    ElMessage.error('仅支持 .docx 格式文件')
    return
  }
  if (file.size > 20 * 1024 * 1024) {
    ElMessage.error('文件大小不能超过 20MB')
    return
  }
  selectedFile.value = file
}

function clearFile() {
  selectedFile.value = null
  if (fileInput.value) fileInput.value.value = ''
}

function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(2) + ' MB'
}

function applyTag(tag) {
  prompt.value = tag.text
}

async function handleSubmit() {
  if (!canSubmit.value) return

  submitting.value = true
  try {
    const res = await processDocument(selectedFile.value, prompt.value)
    ElMessage.success('任务已提交')
    router.push(`/task/${res.task_id}`)
  } catch (err) {
    ElMessage.error(err.message || '提交失败')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.upload-page__main {
  min-height: calc(100vh - 200px);
  padding: 120px 24px 80px;
  background: transparent;
}

.upload-page__container {
  max-width: 800px;
  margin: 0 auto;
}

.upload-page__header {
  text-align: center;
  margin-bottom: 40px;
}

.upload-page__title {
  font-size: 32px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.upload-page__desc {
  font-size: 16px;
  color: var(--text-secondary);
  margin: 0;
}

.upload-card,
.prompt-card {
  background: var(--glass-surface);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
  padding: 32px;
  margin-bottom: 24px;
}

.upload-zone {
  border: 2px dashed rgba(255, 255, 255, 0.55);
  border-radius: var(--radius-lg);
  padding: 48px 24px;
  text-align: center;
  cursor: pointer;
  background: rgba(255, 255, 255, 0.12);
  transition: border-color var(--transition-base), background var(--transition-base);
}

.upload-zone:hover,
.upload-zone--dragover {
  border-color: var(--brand-500);
  background: rgba(99, 102, 241, 0.14);
  box-shadow: inset 0 0 0 4px rgba(99, 102, 241, 0.06), var(--glass-highlight);
}

.upload-zone__input {
  display: none;
}

.upload-zone__icon {
  width: 72px;
  height: 72px;
  border-radius: 20px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.16), rgba(255, 255, 255, 0.34));
  border: 1px solid rgba(255, 255, 255, 0.48);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.50);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--brand-600);
  margin: 0 auto 16px;
}

.upload-zone__title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.upload-zone__desc {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 0;
}

.upload-zone__file {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
  background: rgba(255, 255, 255, 0.30);
  backdrop-filter: blur(12px) saturate(165%);
  -webkit-backdrop-filter: blur(12px) saturate(165%);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-md);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.50);
}

.upload-zone__file-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.44);
  border: 1px solid var(--glass-border);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.50);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--brand-600);
}

.upload-zone__file-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  text-align: left;
}

.upload-zone__file-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.upload-zone__file-size {
  font-size: 13px;
  color: var(--text-secondary);
}

.prompt-card__label {
  display: block;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
}

.prompt-card :deep(.el-textarea__inner) {
  border-radius: var(--radius-md);
  padding: 12px 16px;
  font-size: 15px;
}

.prompt-card__tags {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 16px;
}

.prompt-card__tags-label {
  font-size: 13px;
  color: var(--text-secondary);
}

.prompt-card__tag {
  padding: 6px 12px;
  background: rgba(255, 255, 255, 0.30);
  backdrop-filter: blur(10px) saturate(165%);
  -webkit-backdrop-filter: blur(10px) saturate(165%);
  border: 1px solid var(--glass-border);
  border-radius: 9999px;
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast), box-shadow var(--transition-fast);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.40);
}

.prompt-card__tag:hover {
  background: rgba(99, 102, 241, 0.16);
  color: var(--brand-600);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
}

.upload-page__actions {
  text-align: center;
  margin-bottom: 24px;
}

.upload-page__submit {
  width: 100%;
  max-width: 320px;
  height: 48px;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  border: none;
  font-size: 16px;
  font-weight: 600;
}

.upload-page__submit:disabled {
  opacity: 0.72;
  cursor: not-allowed;
}

.upload-page__security {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-tertiary);
  margin: 0;
}
</style>

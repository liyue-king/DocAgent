<template>
  <div class="task-page">
    <AppNavbar />

    <main class="task-page__main">
      <div class="task-page__container">
        <!-- 处理中 / 重试中 -->
        <div v-if="isProcessing" class="task-card">
          <div v-if="status === 'retrying'" class="task-card__warning">
            <el-icon><Warning /></el-icon>
            <span>校验发现少量偏差，AI 正在进行第 {{ retryCount + 1 }} 次优化</span>
          </div>

          <div class="task-card__header">
            <h2 class="task-card__title">
              {{ status === 'retrying' ? '正在二次优化...' : '正在处理文档...' }}
            </h2>
            <p class="task-card__step">{{ step || '准备开始' }}</p>
          </div>

          <ProgressBar
            :progress="progress"
            :step="step"
            :is-retrying="status === 'retrying'"
          />

          <LogTerminal :logs="displayLogs" />

          <div class="task-card__footer">
            <span class="task-card__eta">预计还需 {{ estimatedTime }} 秒</span>
            <div class="task-card__actions">
              <el-button text @click="router.push('/upload')">返回上传</el-button>
              <el-button type="danger" plain :loading="cancelling" @click="handleCancel">
                取消任务
              </el-button>
            </div>
          </div>
        </div>

        <!-- 成功 -->
        <div v-else-if="status === 'success'" class="result-card result-card--success">
          <AnimatedCheck />
          <h2 class="result-card__title">排版完成</h2>
          <p class="result-card__desc">任务处理完成，耗时 {{ elapsedTime }}</p>

          <div class="result-card__file">
            <el-icon><Document /></el-icon>
            <div class="result-card__file-info">
              <span class="result-card__file-name">文档排版结果</span>
              <span class="result-card__file-size">已生成 · 可下载</span>
            </div>
          </div>

          <ValidationReport :report="validationReport" />

          <div class="result-card__actions">
            <a
              v-if="downloadUrl"
              :href="downloadUrl"
              class="result-card__primary result-card__primary--link"
            >
              下载文档
            </a>
            <el-button
              v-else
              type="primary"
              size="large"
              class="result-card__primary"
              disabled
            >
              下载文档
            </el-button>
            <el-button size="large" @click="router.push('/upload')">再来一单</el-button>
          </div>

          <p class="result-card__hint">点击「下载文档」即可保存排版结果</p>
        </div>

        <!-- 已取消 -->
        <div v-else-if="status === 'cancelled'" class="result-card result-card--error">
          <div class="result-card__icon result-card__icon--error">
            <el-icon><CircleClose /></el-icon>
          </div>
          <h2 class="result-card__title">任务已取消</h2>
          <p class="result-card__desc">该任务已被取消，未产生下载结果</p>
          <div class="result-card__actions">
            <el-button type="primary" size="large" class="result-card__primary" @click="router.push('/upload')">
              返回上传
            </el-button>
          </div>
        </div>

        <!-- 失败 / 过期 / 加载失败 -->
        <div v-else-if="isFailed" class="result-card result-card--error">
          <div class="result-card__icon result-card__icon--error">
            <el-icon><CircleClose /></el-icon>
          </div>
          <h2 class="result-card__title">{{ failTitle }}</h2>
          <p class="result-card__desc">{{ failDesc }}</p>

          <ValidationReport :report="validationReport" />

          <el-collapse v-if="displayLogs.length" class="result-card__logs">
            <el-collapse-item title="查看详细日志">
              <div class="result-card__log-list">
                <p v-for="(log, index) in displayLogs" :key="index">{{ log.message }}</p>
              </div>
            </el-collapse-item>
          </el-collapse>

          <div class="result-card__actions">
            <el-button type="primary" size="large" class="result-card__primary" @click="router.push('/upload')">
              返回上传
            </el-button>
          </div>

          <router-link to="/" class="result-card__back">返回首页</router-link>
        </div>

        <!-- 加载中 -->
        <div v-else class="task-card task-card--loading">
          <el-skeleton :rows="6" animated />
        </div>
      </div>
    </main>

    <AppFooter />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Warning, Document, CircleClose } from '@element-plus/icons-vue'
import AppNavbar from '@/components/AppNavbar.vue'
import AppFooter from '@/components/AppFooter.vue'
import ProgressBar from '@/components/ProgressBar.vue'
import LogTerminal from '@/components/LogTerminal.vue'
import AnimatedCheck from '@/components/AnimatedCheck.vue'
import ValidationReport from '@/components/ValidationReport.vue'
import { useTaskPolling } from '@/composables/useTaskPolling.js'
import { cancelTask } from '@/api/tasks'

const route = useRoute()
const router = useRouter()

const taskId = route.params.id
const startTime = ref(Date.now())
const cancelling = ref(false)

const {
  status,
  progress,
  step,
  logs,
  downloadUrl,
  errorMessage,
  retryCount,
  validationReport,
  startPolling,
  stopPolling,
} = useTaskPolling(taskId, { interval: 2000 })

const isProcessing = computed(() => {
  return (
    !isFailed.value &&
    ['pending', 'retrieving', 'planning', 'executing', 'validating', 'retrying'].includes(status.value)
  )
})

const isFailed = computed(() => {
  return ['failed', 'expired'].includes(status.value) || !!errorMessage.value
})

const failTitle = computed(() => {
  if (status.value === 'expired') return '任务已过期'
  if (status.value === 'failed') return '排版未能完成'
  return '任务加载失败'
})

const failDesc = computed(() => {
  if (status.value === 'expired') return '任务已超过 24 小时生命周期，文件已自动清理'
  return errorMessage.value || '处理过程出现异常，请查看下方日志'
})

// 后端日志为纯文本，统一结构化为 LogTerminal 可读格式
const displayLogs = computed(() =>
  (logs.value || []).map((item) =>
    typeof item === 'string' ? { time: '', level: 'info', message: item } : item
  )
)

const estimatedTime = computed(() => {
  return Math.max(5, Math.ceil((100 - progress.value) / 2))
})

const elapsedTime = computed(() => {
  const seconds = Math.floor((Date.now() - startTime.value) / 1000)
  return `${seconds} 秒`
})

async function handleCancel() {
  try {
    await ElMessageBox.confirm(
      '确定要取消当前任务吗？已执行的修改将无法保存。',
      '取消任务',
      {
        confirmButtonText: '确认取消',
        cancelButtonText: '继续处理',
        type: 'warning',
      }
    )
  } catch {
    return // 用户选择继续处理
  }
  cancelling.value = true
  try {
    await cancelTask(taskId)
    ElMessage.success('任务已取消')
    stopPolling()
    status.value = 'cancelled'
  } catch (err) {
    ElMessage.error(err.message || '取消失败，请重试')
  } finally {
    cancelling.value = false
  }
}

onMounted(() => {
  startPolling()
})
</script>

<style scoped>
.task-page__main {
  min-height: calc(100vh - 200px);
  padding: 120px 24px 80px;
  background: transparent;
}

.task-page__container {
  max-width: 720px;
  margin: 0 auto;
}

.task-card {
  background: var(--glass-surface);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
  padding: 32px;
}

.task-card__warning {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: rgba(245, 158, 11, 0.15);
  border: 1px solid rgba(245, 158, 11, 0.2);
  backdrop-filter: blur(10px) saturate(160%);
  -webkit-backdrop-filter: blur(10px) saturate(160%);
  border-radius: var(--radius-md);
  color: #B45309;
  font-size: 14px;
  margin-bottom: 24px;
}

.task-card__header {
  margin-bottom: 24px;
}

.task-card__title {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.task-card__step {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 0;
}

.task-card__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 24px;
  padding-top: 24px;
  border-top: 1px solid var(--border-color);
}

.task-card__eta {
  font-size: 14px;
  color: var(--text-secondary);
}

.task-card__actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.result-card {
  background: var(--glass-surface);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--glass-shadow-lg), var(--glass-highlight);
  padding: 48px;
  text-align: center;
}

.result-card__title {
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 24px 0 8px;
}

.result-card__desc {
  font-size: 15px;
  color: var(--text-secondary);
  margin: 0 0 32px;
}

.result-card__file {
  display: flex;
  align-items: center;
  gap: 16px;
  max-width: 320px;
  margin: 0 auto 32px;
  padding: 16px;
  background: rgba(255, 255, 255, 0.30);
  backdrop-filter: blur(12px) saturate(165%);
  -webkit-backdrop-filter: blur(12px) saturate(165%);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-md);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.50);
  text-align: left;
}

.result-card__file .el-icon {
  font-size: 32px;
  color: var(--brand-500);
}

.result-card__file-info {
  display: flex;
  flex-direction: column;
}

.result-card__file-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.result-card__file-size {
  font-size: 13px;
  color: var(--text-secondary);
}

.result-card__actions {
  display: flex;
  justify-content: center;
  gap: 16px;
  margin-bottom: 16px;
}

.result-card__primary {
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  border: none;
}

.result-card__primary--link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 120px;
  height: 40px;
  padding: 0 22px;
  border-radius: var(--radius-md);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  text-decoration: none;
  box-shadow: 0 8px 22px rgba(91, 91, 240, 0.30), inset 0 1px 0 rgba(255, 255, 255, 0.35);
  transition: transform var(--transition-fast), box-shadow var(--transition-fast);
}

.result-card__primary--link:hover {
  color: #fff;
  transform: translateY(-1px);
  box-shadow: 0 10px 26px rgba(91, 91, 240, 0.36), inset 0 1px 0 rgba(255, 255, 255, 0.38);
}

.result-card__hint {
  font-size: 13px;
  color: var(--text-tertiary);
  margin: 0;
}

.result-card__icon--error {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  background: rgba(239, 68, 68, 0.12);
  border: 1px solid rgba(239, 68, 68, 0.18);
  backdrop-filter: blur(10px) saturate(160%);
  -webkit-backdrop-filter: blur(10px) saturate(160%);
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto;
  color: var(--error-500);
  font-size: 40px;
}

.result-card__logs {
  max-width: 480px;
  margin: 0 auto 24px;
  text-align: left;
}

.result-card__log-list {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.8;
}

.result-card__back {
  display: inline-block;
  margin-top: 16px;
  font-size: 14px;
  color: var(--text-secondary);
}
</style>

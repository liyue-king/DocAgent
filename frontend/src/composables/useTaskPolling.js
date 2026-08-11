import { ref, onUnmounted } from 'vue'
import { getTaskStatus } from '@/api/tasks'

// SSE 端点需直连后端（EventSource 无法带 Authorization，流端点本身公开）
const BASE = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')

const TERMINAL_STATES = ['success', 'failed', 'expired', 'cancelled']

export function useTaskPolling(taskId, options = {}) {
  const status = ref('pending')
  const progress = ref(0)
  const step = ref('')
  const logs = ref([])
  const downloadUrl = ref(null)
  const errorMessage = ref('')
  const retryCount = ref(0)
  const validationReport = ref(null)

  let timer = null
  let source = null
  const interval = options.interval || 2000

  function applyData(data) {
    status.value = data.status
    progress.value = data.progress || 0
    step.value = data.step || ''
    if (Array.isArray(data.logs)) logs.value = data.logs
    downloadUrl.value = data.download_url || null
    retryCount.value = data.retry_count || 0
    validationReport.value = data.validation_report || null
  }

  function stopPolling() {
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
  }

  function closeStream() {
    if (source) {
      source.close()
      source = null
    }
  }

  async function poll() {
    try {
      const data = await getTaskStatus(taskId)
      applyData(data)
      if (TERMINAL_STATES.includes(data.status)) {
        stopPolling()
        return
      }
    } catch (err) {
      errorMessage.value = err.message
      stopPolling()
      return
    }
    timer = setTimeout(poll, interval)
  }

  // ---- SSE 优先：实时推送，连接失败自动降级 2s 轮询 ----
  function openStream() {
    try {
      source = new EventSource(`${BASE}/task/${taskId}/stream`)
    } catch {
      poll() // 构造失败（极罕见）→ 直接走轮询
      return
    }
    source.addEventListener('status', (event) => {
      const data = JSON.parse(event.data)
      applyData(data)
      if (TERMINAL_STATES.includes(data.status)) {
        closeStream()
      }
    })
    source.addEventListener('log', (event) => {
      // 增量日志：仅追加，避免与全量 logs 相互覆盖
      logs.value = [...(logs.value || []).slice(-49), JSON.parse(event.data)]
    })
    source.addEventListener('error', () => {
      // CONNECTING = 自动重连中（服务端 retry: 3000）；CLOSED = 致命失败 → 降级轮询
      if (source && source.readyState === EventSource.CLOSED) {
        closeStream()
        poll()
      }
    })
  }

  function startPolling() {
    stopPolling()
    closeStream()
    openStream()
  }

  function stopAll() {
    stopPolling()
    closeStream()
  }

  onUnmounted(stopAll)

  return {
    status,
    progress,
    step,
    logs,
    downloadUrl,
    errorMessage,
    retryCount,
    validationReport,
    startPolling,
    stopPolling: stopAll,
  }
}

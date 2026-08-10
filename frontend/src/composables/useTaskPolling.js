import { ref, onUnmounted } from 'vue'
import { getTaskStatus } from '@/api/tasks'

export function useTaskPolling(taskId, options = {}) {
  const status = ref('pending')
  const progress = ref(0)
  const step = ref('')
  const logs = ref([])
  const downloadUrl = ref(null)
  const errorMessage = ref('')
  const retryCount = ref(0)

  let timer = null
  const interval = options.interval || 2000

  async function poll() {
    try {
      const data = await getTaskStatus(taskId)
      status.value = data.status
      progress.value = data.progress || 0
      step.value = data.step || ''
      logs.value = data.logs || []
      downloadUrl.value = data.download_url || null
      retryCount.value = data.retry_count || 0

      const terminalStates = ['success', 'failed', 'expired']
      if (terminalStates.includes(data.status)) {
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

  function startPolling() {
    stopPolling()
    poll()
  }

  function stopPolling() {
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
  }

  onUnmounted(stopPolling)

  return {
    status,
    progress,
    step,
    logs,
    downloadUrl,
    errorMessage,
    retryCount,
    startPolling,
    stopPolling,
  }
}

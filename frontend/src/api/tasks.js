import client from './client'
import { callTool } from './mcp'

export function processDocument(file, prompt) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('prompt', prompt)
  return client.post('/process', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function getTaskStatus(taskId) {
  return callTool('get_task_status_api_v1_task__task_id__get', { task_id: taskId })
}

export function getDownloadUrl(taskId) {
  // 二进制下载无法经 MCP JSON 传输，仍走 HTTP
  return client.get(`/download/${taskId}`, { responseType: 'blob' })
}

export function getTasks(params) {
  return callTool('list_my_tasks_api_v1_tasks_get', { ...params })
}

export function cancelTask(taskId) {
  return callTool('cancel_task_api_v1_task__task_id__cancel_post', { task_id: taskId })
}

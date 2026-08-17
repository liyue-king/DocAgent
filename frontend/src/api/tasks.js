import client from './client'

export function processDocument(file, prompt) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('prompt', prompt)
  return client.post('/process', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 180000,
  })
}

export function getTaskStatus(taskId) {
  return client.get(`/task/${taskId}`)
}

export function getDownloadUrl(taskId) {
  // 二进制下载走 blob
  return client.get(`/download/${taskId}`, { responseType: 'blob' })
}

export function getTasks(params) {
  return client.get('/tasks', { params })
}

export function cancelTask(taskId) {
  return client.post(`/task/${taskId}/cancel`)
}

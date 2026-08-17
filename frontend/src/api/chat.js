import client from './client'

export function sendChat(message) {
  // LLM 生成最长 60s（后端 timeout=60 + 重试 1 次），必须覆盖 axios 全局 30s 默认值
  return client.post('/chat', { message }, { timeout: 120000 })
}

export function getChatHistory(limit = 100) {
  return client.get('/chat/history', { params: { limit } })
}

export function uploadKnowledge(formData) {
  // 用户自定义知识库（独立）
  return client.post('/knowledge', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 180000,
  })
}

export function getKnowledgeStats() {
  return client.get('/knowledge/stats')
}

export function listKnowledgeDocs() {
  return client.get('/knowledge')
}

export function deleteKnowledgeDoc(docId) {
  return client.delete(`/knowledge/${docId}`)
}

// ---- 平台知识库（仅管理员，RAG）----
export function uploadAdminKnowledge(formData) {
  return client.post('/rag/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 180000,
  })
}

export function getAdminKnowledgeStats() {
  return client.get('/rag/stats')
}

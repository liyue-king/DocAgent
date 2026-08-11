import client from './client'
import { callTool } from './mcp'

export function sendChat(message) {
  return callTool('chat_api_v1_chat_post', { message })
}

export function getChatHistory(limit = 100) {
  return callTool('chat_history_api_v1_chat_history_get', { limit })
}

export function uploadKnowledge(formData) {
  // 用户自定义知识库（独立）
  return client.post('/knowledge', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 180000,
  })
}

export function getKnowledgeStats() {
  return callTool('my_knowledge_stats_api_v1_knowledge_stats_get', {})
}

export function listKnowledgeDocs() {
  return callTool('list_my_docs_api_v1_knowledge_get', {})
}

export function deleteKnowledgeDoc(docId) {
  return callTool('delete_my_doc_api_v1_knowledge__doc_id__delete', { doc_id: docId })
}

// ---- 平台知识库（仅管理员，RAG）----
export function uploadAdminKnowledge(formData) {
  return client.post('/rag/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 180000,
  })
}

export function getAdminKnowledgeStats() {
  return callTool('knowledge_stats_api_v1_rag_stats_get', {})
}

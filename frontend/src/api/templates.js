import client from './client'

export function getTemplates() {
  return client.get('/templates')
}

export async function getTemplate(id) {
  // 后端无单模板详情接口，从列表过滤（保持调用方 API 不变）
  const data = await getTemplates()
  const list = data.templates || []
  const target = list.find((t) => t.id === id || String(t.id) === String(id))
  return target ? { templates: [target] } : { templates: [] }
}

export function recommendTemplates(query, topK = 3) {
  return client.post('/templates/recommend', { query, top_k: topK })
}

export function createTemplate(data) {
  return client.post('/templates', data)
}

export function updateTemplate(templateId, data) {
  return client.put(`/templates/${templateId}`, data)
}

export function deleteTemplate(templateId) {
  return client.delete(`/templates/${templateId}`)
}

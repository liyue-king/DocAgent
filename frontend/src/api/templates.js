import { callTool } from './mcp'

export function getTemplates() {
  return callTool('list_templates_api_v1_templates_get', {})
}

export async function getTemplate(id) {
  // 后端无单模板详情接口，从列表过滤（保持调用方 API 不变）
  const data = await getTemplates()
  const list = data.templates || []
  const target = list.find((t) => t.id === id || String(t.id) === String(id))
  return target ? { templates: [target] } : { templates: [] }
}

export function recommendTemplates(query, topK = 3) {
  return callTool('recommend_api_v1_templates_recommend_post', { query, top_k: topK })
}

export function createTemplate(data) {
  return callTool('create_template_api_v1_templates_post', data)
}

export function updateTemplate(templateId, data) {
  return callTool('update_template_api_v1_templates__template_id__put', {
    template_id: templateId,
    ...data,
  })
}

export function deleteTemplate(templateId) {
  return callTool('delete_template_api_v1_templates__template_id__delete', {
    template_id: templateId,
  })
}

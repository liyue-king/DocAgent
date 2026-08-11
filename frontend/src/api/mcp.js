/**
 * 轻量 MCP JSON-RPC 客户端（Streamable HTTP transport）
 *
 * 流程：initialize（获取 Mcp-Session-Id）→ notifications/initialized
 *      → tools/list（结果缓存）→ tools/call
 *
 * 鉴权：登录 token 通过 Authorization: Bearer <JWT> 头随每个请求发送，
 *      后端 FastApiMCP 默认将 authorization 头转发给实际 API 调用。
 *
 * 返回约定：tools/call 的 result.content[0].text 是 JSON 字符串，
 *      解析后按后端业务契约校验 code（HTTP 200 + {"code":N,"msg":...}）。
 */

const MCP_URL = import.meta.env.VITE_MCP_URL || '/mcp'
const PROTOCOL_VERSION = '2025-03-26'
const CLIENT_INFO = { name: 'docagent-frontend', version: '0.1.0' }

let sessionId = null
let initPromise = null
let toolsCache = null
let requestId = 0
let recoveringPromise = null
let sessionGeneration = 0

function getToken() {
  return localStorage.getItem('docagent_token') || ''
}

function buildHeaders() {
  const headers = {
    'Content-Type': 'application/json',
    Accept: 'application/json, text/event-stream',
  }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (sessionId) headers['Mcp-Session-Id'] = sessionId
  return headers
}

function handleUnauthorized() {
  localStorage.removeItem('docagent_token')
  localStorage.removeItem('docagent_user')
  const current = window.location.pathname + window.location.search
  if (!['/login', '/register'].some((p) => current.startsWith(p))) {
    window.location.href = `/login?redirect=${encodeURIComponent(current)}`
  }
}

class McpError extends Error {
  constructor(message, detail = {}) {
    super(message)
    this.name = 'McpError'
    this.detail = detail
  }
}

async function post(body, { skipSessionRetry = false } = {}) {
  const sentGeneration = sessionGeneration
  let resp
  try {
    resp = await fetch(MCP_URL, {
      method: 'POST',
      headers: buildHeaders(),
      body: JSON.stringify(body),
    })
  } catch {
    throw new McpError('无法连接后端服务，请确认网关已启动')
  }

  // 仅成功响应才更新会话 ID，避免错误响应里的旧会话头覆盖新会话
  const newSession = resp.headers.get('mcp-session-id')
  if (newSession && resp.ok) sessionId = newSession

  if (resp.status === 401) {
    handleUnauthorized()
    throw new McpError('登录已过期，请重新登录')
  }

  let data = null
  const text = await resp.text()
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      throw new McpError(`后端返回格式异常（HTTP ${resp.status}）`)
    }
  }

  // 会话失效（后端重启 / 会话过期）：MCP 规范返回 404 + "Session not found"，
  // 部分实现也会用 400 + 错误码 -32600。统一重置会话并重试一次。
  if (!skipSessionRetry && isSessionError(resp, data)) {
    if (sentGeneration === sessionGeneration) {
      // 本请求携带的是旧会话：重置并重新初始化
      await recoverSession()
    }
    // 其他请求已完成恢复时，直接使用新会话重试
    return post(body, { skipSessionRetry: true })
  }

  if (!resp.ok) {
    const message = data?.error?.message || `请求失败（HTTP ${resp.status}）`
    throw new McpError(message, data?.error)
  }

  if (data?.error) {
    throw new McpError(data.error.message || 'MCP 调用失败', data.error)
  }

  return data
}

function isSessionError(resp, data) {
  if (!sessionId) return false
  const message = (data?.error?.message || '').toLowerCase()
  const code = data?.error?.code
  if (resp.status === 404) return true
  if (resp.status === 400 && (code === -32600 || message.includes('session'))) return true
  return false
}

async function recoverSession() {
  if (!recoveringPromise) {
    recoveringPromise = (async () => {
      // 清空会话与工具缓存，重新 initialize 拿新会话（代次 +1 标识一次恢复）
      sessionGeneration += 1
      sessionId = null
      initPromise = null
      toolsCache = null
      await ensureInitialized()
    })().finally(() => {
      recoveringPromise = null
    })
  }
  await recoveringPromise
}

function sendNotification(method, params = {}) {
  // 通知类消息无 id、无响应体，失败不影响主流程
  post({ jsonrpc: '2.0', method, params }).catch(() => {})
}

async function ensureInitialized() {
  if (sessionId) return
  if (!initPromise) {
    initPromise = (async () => {
      await post({
        jsonrpc: '2.0',
        id: nextId(),
        method: 'initialize',
        params: {
          protocolVersion: PROTOCOL_VERSION,
          capabilities: {},
          clientInfo: CLIENT_INFO,
        },
      })
      sendNotification('notifications/initialized')
    })().finally(() => {
      initPromise = null
    })
  }
  await initPromise
}

function nextId() {
  requestId += 1
  return requestId
}

/**
 * 拉取（并缓存）MCP 工具列表，返回 [{name, description, inputSchema}]。
 */
export async function listTools(force = false) {
  if (toolsCache && !force) return toolsCache
  await ensureInitialized()
  const data = await post({
    jsonrpc: '2.0',
    id: nextId(),
    method: 'tools/list',
    params: {},
  })
  toolsCache = data?.result?.tools || []
  return toolsCache
}

function extractText(content) {
  if (!Array.isArray(content)) return ''
  return content.map((c) => c.text || '').join('')
}

/**
 * 调用 MCP 工具。
 *
 * @param {string} name 工具名（后端 OpenAPI operationId）
 * @param {object} args 工具参数
 * @returns {Promise<any>} 解析后的响应对象；业务失败（code !== 0）时 reject
 */
export async function callTool(name, args = {}) {
  // 按用户约定的链路先拉取工具清单（已缓存，仅首次产生一次 tools/list）
  await listTools().catch(() => {})
  const data = await post({
    jsonrpc: '2.0',
    id: nextId(),
    method: 'tools/call',
    params: { name, arguments: args },
  })
  const result = data?.result || {}
  if (result.isError) {
    const message = extractText(result.content) || `工具调用失败：${name}`
    throw new McpError(message)
  }
  const text = extractText(result.content)
  let parsed
  try {
    parsed = JSON.parse(text)
  } catch {
    return text
  }
  // 后端业务契约：HTTP 200 + {"code":N,"msg":...}，N !== 0 视为失败
  if (parsed && typeof parsed.code === 'number' && parsed.code !== 0) {
    throw new McpError(parsed.msg || '请求失败')
  }
  return parsed
}

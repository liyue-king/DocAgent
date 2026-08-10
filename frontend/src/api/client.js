import axios from 'axios'

const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器：附加 token
client.interceptors.request.use((config) => {
  const token = localStorage.getItem('docagent_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器：统一错误处理
client.interceptors.response.use(
  (response) => {
    // 后端业务错误约定：HTTP 200 + {"code":N,"msg":...}（N != 0 视为失败）
    const data = response.data
    if (data && typeof data.code === 'number' && data.code !== 0) {
      return Promise.reject(new Error(data.msg || '请求失败'))
    }
    return data
  },
  (error) => {
    if (error.response?.status === 401) {
      // token 失效：清除本地登录态并跳转登录页
      localStorage.removeItem('docagent_token')
      localStorage.removeItem('docagent_user')
      const current = window.location.pathname + window.location.search
      if (!['/login', '/register'].some((p) => current.startsWith(p))) {
        window.location.href = `/login?redirect=${encodeURIComponent(current)}`
      }
    }
    const message = error.response?.data?.msg || error.message || '请求失败'
    return Promise.reject(new Error(message))
  }
)

export default client

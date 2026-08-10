import { ref, computed } from 'vue'
import { getCurrentUser } from '@/api/auth.js'

const token = ref(localStorage.getItem('docagent_token') || '')
const user = ref(JSON.parse(localStorage.getItem('docagent_user') || 'null'))

export function useAuthStore() {
  const isLoggedIn = computed(() => !!token.value)
  const isAdmin = computed(() => !!user.value?.is_admin)

  function setAuth(newToken, newUser) {
    token.value = newToken
    user.value = newUser
    localStorage.setItem('docagent_token', newToken)
    localStorage.setItem('docagent_user', JSON.stringify(newUser))
  }

  function clearAuth() {
    token.value = ''
    user.value = null
    localStorage.removeItem('docagent_token')
    localStorage.removeItem('docagent_user')
  }

  async function fetchCurrentUser() {
    if (!token.value) return null
    try {
      const data = await getCurrentUser()
      user.value = data.user
      localStorage.setItem('docagent_user', JSON.stringify(data.user))
      return data.user
    } catch {
      return null
    }
  }

  return {
    token,
    user,
    isLoggedIn,
    isAdmin,
    setAuth,
    clearAuth,
    fetchCurrentUser,
  }
}

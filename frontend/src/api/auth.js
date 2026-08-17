import client from './client'

export function sendEmailCode(email) {
  return client.post('/auth/code', { email })
}

export function login(data) {
  return client.post('/auth/login', data)
}

export function register(data) {
  return client.post('/auth/register', data)
}

export function getCurrentUser() {
  return client.get('/auth/me')
}

export function logout() {
  return client.post('/auth/logout')
}

export function changePassword(oldPassword, newPassword) {
  return client.post('/auth/change-password', {
    old_password: oldPassword,
    new_password: newPassword,
  })
}

export function changeEmail(email, code) {
  return client.post('/auth/change-email', { email, code })
}

export function resetPassword(email, code, password) {
  return client.post('/auth/reset', { email, code, password })
}

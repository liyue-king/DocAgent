import { callTool } from './mcp'

export function sendEmailCode(email) {
  return callTool('send_email_code_api_v1_auth_code_post', { email })
}

export function login(data) {
  return callTool('login_api_v1_auth_login_post', data)
}

export function register(data) {
  return callTool('register_api_v1_auth_register_post', data)
}

export function getCurrentUser() {
  return callTool('me_api_v1_auth_me_get', {})
}

export function logout() {
  return callTool('logout_api_v1_auth_logout_post', {})
}

export function changePassword(oldPassword, newPassword) {
  return callTool('change_password_api_v1_auth_change_password_post', {
    old_password: oldPassword,
    new_password: newPassword,
  })
}

export function changeEmail(email, code) {
  return callTool('change_email_api_v1_auth_change_email_post', { email, code })
}

export function resetPassword(email, code, password) {
  return callTool('reset_password_api_v1_auth_reset_post', { email, code, password })
}

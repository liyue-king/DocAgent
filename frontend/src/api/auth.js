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

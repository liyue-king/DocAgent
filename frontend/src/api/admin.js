import { callTool } from './mcp'

export function listUsers(params = {}) {
  return callTool('list_users_api_v1_admin_users_get', {
    search: params.search || '',
    limit: params.limit || 50,
    offset: params.offset || 0,
  })
}

export function updateUser(userId, data) {
  return callTool('update_user_api_v1_admin_users__user_id__patch', {
    user_id: userId,
    ...data,
  })
}

export function getUserOrders(userId) {
  return callTool('user_orders_api_v1_admin_users__user_id__orders_get', {
    user_id: userId,
  })
}

export function markOrderPaid(orderId) {
  return callTool('mark_order_paid_api_v1_admin_orders__order_id__mark_paid_post', {
    order_id: orderId,
  })
}

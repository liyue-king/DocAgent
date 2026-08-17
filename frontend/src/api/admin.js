import client from './client'

export function listUsers(params = {}) {
  return client.get('/admin/users', {
    params: {
      search: params.search || '',
      limit: params.limit || 50,
      offset: params.offset || 0,
    },
  })
}

export function updateUser(userId, data) {
  return client.patch(`/admin/users/${userId}`, data)
}

export function getUserOrders(userId) {
  return client.get(`/admin/users/${userId}/orders`)
}

export function markOrderPaid(orderId) {
  return client.post(`/admin/orders/${orderId}/mark-paid`)
}

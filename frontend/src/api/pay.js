import client from './client'

export function createPayment(planId) {
  return client.post('/pay/create', { plan_id: planId })
}

export function queryPayment(orderId) {
  return client.get(`/pay/query/${orderId}`)
}

export function getMyOrders() {
  return client.get('/pay/orders')
}

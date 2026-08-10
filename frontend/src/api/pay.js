import { callTool } from './mcp'

export function createPayment(planId) {
  return callTool('create_payment_api_v1_pay_create_post', { plan_id: planId })
}

export function queryPayment(orderId) {
  return callTool('query_payment_api_v1_pay_query__order_id__get', { order_id: orderId })
}

export function getMyOrders() {
  return callTool('my_orders_api_v1_pay_orders_get', {})
}

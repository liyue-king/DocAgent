<template>
  <div class="user-center">
    <AppNavbar />

    <main class="user-center__main">
      <div class="user-center__container">
        <div class="user-center__header">
          <div>
            <h1 class="user-center__title">个人中心</h1>
            <p class="user-center__desc">账户资料、积分明细与安全设置</p>
          </div>
        </div>

        <div class="user-center__grid">
          <aside class="user-center__side">
            <div class="user-center__card user-center__profile">
              <el-avatar :size="64" :icon="UserFilled" />
              <div class="user-center__profile-name">{{ user?.email || '用户' }}</div>
              <div class="user-center__profile-credits">
                <span class="user-center__credits-num">{{ user?.credits_balance ?? 0 }}</span> 次可用额度
              </div>
              <el-tag v-if="user?.is_admin" type="warning" size="small" round>管理员</el-tag>
              <el-tag v-else size="small" round>普通用户</el-tag>
            </div>

            <nav class="user-center__menu">
              <button
                v-for="item in menuItems"
                :key="item.key"
                class="user-center__menu-item"
                :class="{ 'user-center__menu-item--active': activeTab === item.key }"
                @click="activeTab = item.key"
              >
                <el-icon><component :is="item.icon" /></el-icon>
                <span>{{ item.label }}</span>
              </button>
            </nav>
          </aside>

          <section class="user-center__content">
            <!-- 积分明细 -->
            <div v-if="activeTab === 'credits'" class="user-center__card">
              <h2 class="user-center__section-title">积分明细</h2>
              <el-table v-if="creditLogs.length > 0" :data="creditLogs" style="width: 100%">
                <el-table-column label="时间" width="180">
                  <template #default="{ row }">
                    {{ (row.created_at || '').replace('T', ' ').slice(0, 16) }}
                  </template>
                </el-table-column>
                <el-table-column label="动作" width="140">
                  <template #default="{ row }">
                    <el-tag size="small" :type="actionTagType(row.action)" round>
                      {{ actionLabel(row.action) }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="变动" width="100" align="right">
                  <template #default="{ row }">
                    <span :class="row.amount >= 0 ? 'user-center__income' : 'user-center__expense'">
                      {{ row.amount >= 0 ? '+' : '' }}{{ row.amount }}
                    </span>
                  </template>
                </el-table-column>
                <el-table-column label="变动后余额" width="120" align="right">
                  <template #default="{ row }">{{ row.balance_after }}</template>
                </el-table-column>
              </el-table>
              <EmptyState
                v-else
                title="暂无积分流水"
                description="提交任务或充值后，这里会展示每一笔积分变动"
              />
            </div>

            <!-- 修改密码 -->
            <div v-if="activeTab === 'password'" class="user-center__card">
              <h2 class="user-center__section-title">修改密码</h2>
              <el-form
                ref="passwordFormRef"
                :model="passwordForm"
                :rules="passwordRules"
                label-width="90px"
                class="user-center__form"
              >
                <el-form-item label="原密码" prop="oldPassword">
                  <el-input
                    v-model="passwordForm.oldPassword"
                    type="password"
                    show-password
                    placeholder="请输入当前密码"
                  />
                </el-form-item>
                <el-form-item label="新密码" prop="newPassword">
                  <el-input
                    v-model="passwordForm.newPassword"
                    type="password"
                    show-password
                    placeholder="6-64 位新密码"
                  />
                </el-form-item>
                <el-form-item label="确认新密码" prop="confirmPassword">
                  <el-input
                    v-model="passwordForm.confirmPassword"
                    type="password"
                    show-password
                    placeholder="再次输入新密码"
                  />
                </el-form-item>
                <el-form-item>
                  <el-button type="primary" :loading="passwordSubmitting" @click="handleChangePassword">
                    确认修改
                  </el-button>
                </el-form-item>
              </el-form>
              <p class="user-center__tip">修改成功后，其他设备的登录状态将全部失效，需重新登录。</p>
            </div>

            <!-- 修改邮箱 -->
            <div v-if="activeTab === 'email'" class="user-center__card">
              <h2 class="user-center__section-title">修改邮箱</h2>
              <el-form
                ref="emailFormRef"
                :model="emailForm"
                :rules="emailRules"
                label-width="90px"
                class="user-center__form"
              >
                <el-form-item label="当前邮箱">
                  <el-input :model-value="user?.email || ''" disabled />
                </el-form-item>
                <el-form-item label="新邮箱" prop="email">
                  <el-input v-model="emailForm.email" placeholder="请输入新邮箱" />
                </el-form-item>
                <el-form-item label="验证码" prop="code">
                  <div class="user-center__code-row">
                    <el-input v-model="emailForm.code" placeholder="6 位验证码" maxlength="6" />
                    <el-button :disabled="codeCountdown > 0" @click="handleSendCode">
                      {{ codeCountdown > 0 ? `${codeCountdown}s` : '获取验证码' }}
                    </el-button>
                  </div>
                </el-form-item>
                <el-form-item>
                  <el-button type="primary" :loading="emailSubmitting" @click="handleChangeEmail">
                    确认修改
                  </el-button>
                </el-form-item>
              </el-form>
              <p class="user-center__tip">验证码将发送至新邮箱，修改后需使用新邮箱登录。</p>
            </div>

            <!-- 我的订单 -->
            <div v-if="activeTab === 'orders'" class="user-center__card">
              <h2 class="user-center__section-title">我的订单</h2>
              <el-alert
                v-if="pendingOrders.length > 0"
                type="warning"
                :closable="false"
                show-icon
                class="user-center__order-alert"
              >
                你有 {{ pendingOrders.length }} 笔订单尚未支付，支付成功后额度会自动到账
              </el-alert>
              <el-table v-if="orders.length > 0" :data="orders" style="width: 100%">
                <el-table-column prop="order_id" label="订单号" min-width="200" />
                <el-table-column label="套餐" width="140">
                  <template #default="{ row }">{{ row.plan_name || '—' }}</template>
                </el-table-column>
                <el-table-column prop="credits" label="积分" width="100" align="right" />
                <el-table-column label="金额" width="110" align="right">
                  <template #default="{ row }">¥{{ (row.amount / 100).toFixed(2) }}</template>
                </el-table-column>
                <el-table-column label="状态" width="110">
                  <template #default="{ row }">
                    <el-tag :type="orderStatusType(row.status)" size="small" round>
                      {{ orderStatusLabel(row.status) }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="时间" width="170">
                  <template #default="{ row }">
                    {{ (row.created_at || '').replace('T', ' ').slice(0, 16) }}
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="190" fixed="right">
                  <template #default="{ row }">
                    <el-button
                      text
                      type="primary"
                      :loading="refreshingId === row.order_id"
                      @click="refreshOrder(row)"
                    >
                      刷新状态
                    </el-button>
                    <el-button
                      v-if="row.status === 'pending'"
                      text
                      type="warning"
                      @click="continuePay(row)"
                    >
                      继续支付
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>
              <EmptyState
                v-else
                title="暂无订单"
                description="前往定价页购买积分套餐后，订单会显示在这里"
              />
            </div>
          </section>
        </div>
      </div>
    </main>

    <AppFooter />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { UserFilled, Coin, Lock, Message, Tickets } from '@element-plus/icons-vue'
import AppNavbar from '@/components/AppNavbar.vue'
import AppFooter from '@/components/AppFooter.vue'
import EmptyState from '@/components/EmptyState.vue'
import { useAuthStore } from '@/stores/auth.js'
import { sendEmailCode, changePassword, changeEmail, getCurrentUser } from '@/api/auth.js'
import { createPayment, getMyOrders, queryPayment } from '@/api/pay.js'

const { user, setAuth } = useAuthStore()
const route = useRoute()

const activeTab = ref('credits')
const menuItems = [
  { key: 'credits', label: '积分明细', icon: Coin },
  { key: 'password', label: '修改密码', icon: Lock },
  { key: 'email', label: '修改邮箱', icon: Message },
  { key: 'orders', label: '我的订单', icon: Tickets },
]

const creditLogs = ref([])
const orders = ref([])
const refreshingId = ref('')

const pendingOrders = computed(() => orders.value.filter((o) => o.status === 'pending'))

const actionLabels = {
  register: '注册赠送',
  task_consume: '任务消费',
  recharge: '充值到账',
  admin_adjust: '管理员调整',
}

function actionLabel(action) {
  return actionLabels[action] || action
}

function actionTagType(action) {
  if (action === 'task_consume') return 'danger'
  if (action === 'recharge' || action === 'admin_adjust') return 'success'
  return 'info'
}

async function loadMe() {
  try {
    const data = await getCurrentUser()
    if (data.user) {
      setAuth(localStorage.getItem('docagent_token'), data.user)
      creditLogs.value = data.credit_logs || []
    }
  } catch {
    creditLogs.value = []
  }
}

const passwordFormRef = ref()
const passwordSubmitting = ref(false)
const passwordForm = reactive({ oldPassword: '', newPassword: '', confirmPassword: '' })
const passwordRules = {
  oldPassword: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, max: 64, message: '密码长度 6-64 位', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (value !== passwordForm.newPassword) callback(new Error('两次输入的密码不一致'))
        else callback()
      },
      trigger: 'blur',
    },
  ],
}

async function handleChangePassword() {
  await passwordFormRef.value.validate()
  passwordSubmitting.value = true
  try {
    const data = await changePassword(passwordForm.oldPassword, passwordForm.newPassword)
    setAuth(data.token, user.value)
    passwordForm.oldPassword = ''
    passwordForm.newPassword = ''
    passwordForm.confirmPassword = ''
    ElMessage.success(data.msg || '密码修改成功')
  } catch (err) {
    ElMessage.error(err.message || '密码修改失败')
  } finally {
    passwordSubmitting.value = false
  }
}

const emailFormRef = ref()
const emailSubmitting = ref(false)
const codeCountdown = ref(0)
let countdownTimer = null
const emailForm = reactive({ email: '', code: '' })
const emailRules = {
  email: [
    { required: true, message: '请输入新邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
  ],
  code: [
    { required: true, message: '请输入验证码', trigger: 'blur' },
    { min: 6, max: 6, message: '验证码为 6 位数字', trigger: 'blur' },
  ],
}

async function handleSendCode() {
  if (!emailForm.email) {
    ElMessage.warning('请先填写新邮箱')
    return
  }
  try {
    const data = await sendEmailCode(emailForm.email)
    ElMessage.success(data.msg || '验证码已发送')
    codeCountdown.value = 60
    countdownTimer = setInterval(() => {
      codeCountdown.value -= 1
      if (codeCountdown.value <= 0) clearInterval(countdownTimer)
    }, 1000)
  } catch (err) {
    ElMessage.error(err.message || '验证码发送失败')
  }
}

async function handleChangeEmail() {
  await emailFormRef.value.validate()
  emailSubmitting.value = true
  try {
    const data = await changeEmail(emailForm.email, emailForm.code)
    setAuth(data.token, data.user)
    emailForm.code = ''
    ElMessage.success(data.msg || '邮箱修改成功')
  } catch (err) {
    ElMessage.error(err.message || '邮箱修改失败')
  } finally {
    emailSubmitting.value = false
  }
}

async function loadOrders() {
  try {
    const data = await getMyOrders()
    orders.value = data.orders || data || []
  } catch (err) {
    orders.value = []
    ElMessage.error(err.message || '订单加载失败')
  }
}

function orderStatusLabel(status) {
  const map = { paid: '已支付', pending: '待支付', closed: '已关闭', failed: '失败' }
  return map[status] || status || '未知'
}

function orderStatusType(status) {
  if (status === 'paid') return 'success'
  if (status === 'pending') return 'warning'
  return 'info'
}

async function refreshOrder(row) {
  refreshingId.value = row.order_id
  try {
    const data = await queryPayment(row.order_id)
    const updated = data.order
    const idx = orders.value.findIndex((o) => o.order_id === row.order_id)
    if (idx !== -1) orders.value.splice(idx, 1, updated)
    if (updated.status === 'paid') {
      ElMessage.success(`支付成功，已到账 ${updated.credits} 次额度`)
      loadMe()
    } else {
      ElMessage.info('该订单仍为待支付状态')
    }
  } catch (err) {
    ElMessage.error(err.message || '状态刷新失败')
  } finally {
    refreshingId.value = ''
  }
}

async function continuePay(row) {
  try {
    const data = await createPayment(row.plan_id)
    window.location.href = data.pay_url
  } catch (err) {
    ElMessage.error(err.message || '下单失败')
  }
}

onMounted(async () => {
  const tab = route.query.tab
  if (tab && menuItems.some((item) => item.key === tab)) {
    activeTab.value = tab
  }
  await loadMe()
  loadOrders()
})

onUnmounted(() => {
  if (countdownTimer) clearInterval(countdownTimer)
})
</script>

<style scoped>
.user-center__main {
  min-height: calc(100vh - 200px);
  padding: 120px 24px 80px;
  background: transparent;
}

.user-center__container {
  max-width: 1000px;
  margin: 0 auto;
}

.user-center__header {
  margin-bottom: 32px;
}

.user-center__title {
  font-size: 32px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.user-center__desc {
  font-size: 16px;
  color: var(--text-secondary);
  margin: 0;
}

.user-center__grid {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 24px;
  align-items: start;
}

.user-center__card {
  background: var(--glass-surface);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
  padding: 24px;
}

.user-center__side {
  display: flex;
  flex-direction: column;
  gap: 16px;
  position: sticky;
  top: 100px;
}

.user-center__profile {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  text-align: center;
}

.user-center__profile-name {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  word-break: break-all;
}

.user-center__profile-credits {
  font-size: 13px;
  color: var(--text-secondary);
}

.user-center__credits-num {
  font-size: 22px;
  font-weight: 700;
  color: var(--brand-600);
}

.user-center__menu {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.user-center__menu-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  background: transparent;
  font-size: 14px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
  text-align: left;
}

.user-center__menu-item:hover {
  color: var(--brand-600);
  background: rgba(255, 255, 255, 0.4);
}

.user-center__menu-item--active {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.16), rgba(255, 255, 255, 0.30));
  color: var(--brand-700);
  border-color: var(--brand-500);
}

.user-center__section-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 20px;
}

.user-center__form {
  max-width: 420px;
}

.user-center__code-row {
  display: flex;
  gap: 10px;
  width: 100%;
}

.user-center__income {
  color: var(--success-color, #16a34a);
  font-weight: 600;
}

.user-center__expense {
  color: var(--danger-color, #dc2626);
  font-weight: 600;
}

.user-center__tip {
  font-size: 12px;
  color: var(--text-tertiary);
  margin: 12px 0 0;
}

.user-center__order-alert {
  margin-bottom: 16px;
}

@media (max-width: 768px) {
  .user-center__grid {
    grid-template-columns: 1fr;
  }

  .user-center__side {
    position: static;
  }

  .user-center__menu {
    flex-direction: row;
    flex-wrap: wrap;
  }
}
</style>

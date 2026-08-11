<template>
  <div class="admin-users-page">
    <AppNavbar />

    <main class="admin-users-page__main">
      <div class="admin-users-page__container">
        <div class="admin-users-page__header">
          <div>
            <h1 class="admin-users-page__title">用户管理</h1>
            <p class="admin-users-page__desc">
              搜索用户、调整余额/账号状态，或查看订单并补登支付到账
            </p>
          </div>
          <el-input
            v-model="search"
            placeholder="搜索邮箱或用户 ID"
            clearable
            :prefix-icon="Search"
            class="admin-users-page__search"
            @keyup.enter="loadUsers(0)"
            @clear="loadUsers(0)"
          >
            <template #append>
              <el-button :icon="Search" @click="loadUsers(0)">搜索</el-button>
            </template>
          </el-input>
        </div>

        <div class="admin-users-card">
          <el-table v-if="users.length > 0" :data="users" style="width: 100%" v-loading="loading">
            <el-table-column prop="id" label="ID" width="80" />
            <el-table-column prop="email" label="邮箱" min-width="220">
              <template #default="{ row }">
                <span class="admin-users-page__email">{{ row.email || '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="credits_balance" label="余额（次）" width="110" align="right" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="row.is_active ? 'success' : 'danger'" size="small" round>
                  {{ row.is_active ? '启用' : '禁用' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="角色" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.is_admin" type="warning" size="small" round>管理员</el-tag>
                <el-tag v-else type="info" size="small" round>普通用户</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="注册时间" width="170">
              <template #default="{ row }">
                {{ formatDate(row.created_at) }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="170" fixed="right">
              <template #default="{ row }">
                <el-button text type="primary" @click="openEdit(row)">编辑</el-button>
                <el-button text type="primary" @click="openOrders(row)">订单</el-button>
              </template>
            </el-table-column>
          </el-table>

          <EmptyState
            v-else-if="!loading"
            title="没有找到用户"
            description="换个关键词试试，支持按邮箱或用户 ID 搜索"
          />

          <div v-if="total > 0" class="admin-users-page__pager">
            <el-pagination
              layout="total, prev, pager, next"
              :total="total"
              :page-size="limit"
              :current-page="currentPage"
              background
              @current-change="loadUsers"
            />
          </div>
        </div>
      </div>
    </main>

    <AppFooter />

    <!-- 编辑用户 -->
    <el-dialog v-model="editVisible" title="编辑用户" width="480px" destroy-on-close>
      <div v-if="editingUser" class="admin-users-page__dialog">
        <div class="admin-users-page__dialog-email">{{ editingUser.email }}</div>

        <el-form label-width="110px">
          <el-form-item label="积分余额">
            <el-input-number
              v-model="editForm.credits_balance"
              :min="0"
              :max="1000000"
              :step="10"
              controls-position="right"
              style="width: 100%"
            />
            <p class="admin-users-page__hint">直接设置调整后的余额，系统会自动记录积分流水</p>
          </el-form-item>

          <el-form-item label="账号状态">
            <el-switch
              v-model="editForm.is_active"
              active-text="启用"
              inactive-text="禁用"
              inline-prompt
            />
          </el-form-item>

          <el-form-item label="管理员">
            <el-switch
              v-model="editForm.is_admin"
              active-text="是"
              inactive-text="否"
              inline-prompt
            />
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSaveUser">保存修改</el-button>
      </template>
    </el-dialog>

    <!-- 用户订单 -->
    <el-dialog v-model="ordersVisible" title="用户订单" width="760px" destroy-on-close>
      <el-table v-if="orders.length > 0" :data="orders" style="width: 100%" v-loading="ordersLoading">
        <el-table-column prop="order_id" label="订单号" min-width="190" show-overflow-tooltip />
        <el-table-column prop="plan_name" label="套餐" width="110" />
        <el-table-column prop="credits" label="积分" width="80" align="right" />
        <el-table-column label="金额" width="90" align="right">
          <template #default="{ row }">¥{{ (row.amount / 100).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="orderStatusType(row.status)" size="small" round>
              {{ orderStatusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="150">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'pending'"
              text
              type="success"
              :loading="markingId === row.order_id"
              @click="handleMarkPaid(row)"
            >
              补登到账
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <EmptyState
        v-else
        title="该用户暂无订单"
        description="用户下单后，订单会显示在这里"
      />
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import AppNavbar from '@/components/AppNavbar.vue'
import AppFooter from '@/components/AppFooter.vue'
import EmptyState from '@/components/EmptyState.vue'
import { getUserOrders, listUsers, markOrderPaid, updateUser } from '@/api/admin.js'

const search = ref('')
const users = ref([])
const total = ref(0)
const limit = ref(50)
const currentPage = ref(1)
const loading = ref(false)

const editVisible = ref(false)
const editingUser = ref(null)
const saving = ref(false)
const editForm = reactive({ credits_balance: 0, is_active: true, is_admin: false })

const ordersVisible = ref(false)
const orders = ref([])
const ordersLoading = ref(false)
const markingId = ref('')
const ordersUser = ref(null)

async function loadUsers(page = 1) {
  loading.value = true
  try {
    const offset = (page - 1) * limit.value
    const data = await listUsers({
      search: search.value.trim(),
      limit: limit.value,
      offset,
    })
    users.value = data.users || []
    total.value = data.total || 0
    currentPage.value = page
  } catch (err) {
    ElMessage.error(err.message || '用户列表加载失败')
  } finally {
    loading.value = false
  }
}

function formatDate(value) {
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 16)
}

function openEdit(row) {
  editingUser.value = row
  editForm.credits_balance = row.credits_balance
  editForm.is_active = row.is_active
  editForm.is_admin = row.is_admin
  editVisible.value = true
}

async function handleSaveUser() {
  if (editingUser.value == null) return
  saving.value = true
  try {
    const data = await updateUser(editingUser.value.id, {
      credits_balance: editForm.credits_balance,
      is_active: editForm.is_active,
      is_admin: editForm.is_admin,
    })
    ElMessage.success(data.msg || '用户信息已更新')
    editVisible.value = false
    loadUsers(currentPage.value)
  } catch (err) {
    ElMessage.error(err.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function openOrders(row) {
  ordersUser.value = row
  ordersVisible.value = true
  orders.value = []
  ordersLoading.value = true
  try {
    const data = await getUserOrders(row.id)
    orders.value = data.orders || []
  } catch (err) {
    ElMessage.error(err.message || '订单加载失败')
  } finally {
    ordersLoading.value = false
  }
}

function orderStatusLabel(status) {
  const map = { paid: '已支付', pending: '待支付', closed: '已关闭', failed: '失败' }
  return map[status] || status
}

function orderStatusType(status) {
  if (status === 'paid') return 'success'
  if (status === 'pending') return 'warning'
  return 'info'
}

async function handleMarkPaid(row) {
  try {
    await ElMessageBox.confirm(
      `确认将订单 ${row.order_id} 补登为已支付并发放 ${row.credits} 次额度吗？`,
      '补登到账',
      { type: 'warning', confirmButtonText: '确认到账', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  markingId.value = row.order_id
  try {
    const data = await markOrderPaid(row.order_id)
    ElMessage.success(data.msg || '补登成功')
    const user = users.value.find((u) => u.id === ordersUser.value?.id)
    if (user) {
      user.credits_balance = (user.credits_balance || 0) + row.credits
    }
    if (ordersUser.value) openOrders(ordersUser.value)
  } catch (err) {
    ElMessage.error(err.message || '补登失败')
  } finally {
    markingId.value = ''
  }
}

onMounted(() => loadUsers(1))
</script>

<style scoped>
.admin-users-page__main {
  min-height: calc(100vh - 200px);
  padding: 120px 24px 80px;
  background: transparent;
}

.admin-users-page__container {
  max-width: 1080px;
  margin: 0 auto;
}

.admin-users-page__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 24px;
}

.admin-users-page__title {
  font-size: 32px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.admin-users-page__desc {
  font-size: 15px;
  color: var(--text-secondary);
  margin: 0;
}

.admin-users-page__search {
  width: 320px;
}

.admin-users-card {
  background: var(--glass-surface);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
  overflow: hidden;
  padding: 8px 16px 16px;
}

.admin-users-page__email {
  font-weight: 500;
}

.admin-users-page__pager {
  display: flex;
  justify-content: flex-end;
  padding-top: 16px;
}

.admin-users-page__dialog-email {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  text-align: center;
  margin-bottom: 20px;
  word-break: break-all;
}

.admin-users-page__hint {
  font-size: 12px;
  color: var(--text-tertiary);
  margin: 6px 0 0;
  width: 100%;
}

@media (max-width: 768px) {
  .admin-users-page__header {
    flex-direction: column;
    align-items: stretch;
  }

  .admin-users-page__search {
    width: 100%;
  }
}
</style>

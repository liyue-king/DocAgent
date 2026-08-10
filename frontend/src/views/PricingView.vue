<template>
  <div class="pricing-page">
    <AppNavbar />

    <main class="pricing-page__main">
      <div class="pricing-page__container">
        <div class="pricing-page__header">
          <h1 class="pricing-page__title">简单透明的定价</h1>
          <p class="pricing-page__desc">按文档处理次数付费，无隐藏费用</p>
        </div>

        <div class="pricing-grid">
          <div
            v-for="plan in plans"
            :key="plan.id"
            class="pricing-card"
            :class="{ 'pricing-card--featured': plan.featured }"
          >
            <div v-if="plan.featured" class="pricing-card__badge">最受欢迎</div>
            <h3 class="pricing-card__name">{{ plan.name }}</h3>
            <p class="pricing-card__desc">{{ plan.description }}</p>
            <div class="pricing-card__price">
              <span class="pricing-card__currency">¥</span>
              <span class="pricing-card__amount">{{ plan.price }}</span>
              <span class="pricing-card__period">/月</span>
            </div>
            <ul class="pricing-card__features">
              <li v-for="feature in plan.features" :key="feature">
                <el-icon><Check /></el-icon>
                <span>{{ feature }}</span>
              </li>
            </ul>
            <el-button
              :type="plan.featured ? 'primary' : 'default'"
              size="large"
              class="pricing-card__btn"
              @click="choosePlan(plan)"
            >
              {{ plan.cta }}
            </el-button>
          </div>
        </div>

        <div class="faq-section">
          <h2 class="faq-section__title">常见问题</h2>
          <el-collapse class="faq-section__list">
            <el-collapse-item title="如何计费？">
              <p>我们按成功处理的文档次数计费。每次上传并处理完成一个文档，消耗一次额度。免费版每月 10 次，超出后需要升级套餐。</p>
            </el-collapse-item>
            <el-collapse-item title="支持退款吗？">
              <p>支持 7 天无理由退款。如果你对我们的服务不满意，可以联系客服申请全额退款。</p>
            </el-collapse-item>
            <el-collapse-item title="可以取消订阅吗？">
              <p>可以随时在账户设置中取消订阅。取消后，当月剩余额度仍然有效，下个月不再扣费。</p>
            </el-collapse-item>
          </el-collapse>
        </div>
      </div>
    </main>

    <AppFooter />
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Check } from '@element-plus/icons-vue'
import AppNavbar from '@/components/AppNavbar.vue'
import AppFooter from '@/components/AppFooter.vue'
import { createPayment, queryPayment } from '@/api/pay.js'
import { useAuthStore } from '@/stores/auth.js'

const route = useRoute()
const router = useRouter()
const { isLoggedIn, fetchCurrentUser } = useAuthStore()

const plans = [
  {
    id: 'free',
    name: '免费版',
    description: '适合个人轻度使用',
    price: 0,
    features: ['每月 10 次处理', '基础模板', '标准处理速度', '24小时文件保留'],
    cta: '免费开始',
    featured: false,
  },
  {
    id: 'pro',
    name: '专业版',
    description: '适合频繁使用的个人和团队',
    price: 29,
    features: ['每月 100 次处理', '全部专业模板', '优先处理队列', '7天文件保留', 'API 接入'],
    cta: '立即订阅',
    featured: true,
  },
  {
    id: 'team',
    name: '团队版',
    description: '适合企业级需求',
    price: 99,
    features: ['每月 500 次处理', '全部模板 + 自定义', '专属客服支持', '30天文件保留', '团队协作功能'],
    cta: '联系销售',
    featured: false,
  },
]

async function choosePlan(plan) {
  if (plan.id === 'free') {
    router.push('/upload')
    return
  }
  if (!isLoggedIn.value) {
    ElMessage.warning('请先登录后再购买套餐')
    router.push(`/login?redirect=${encodeURIComponent('/pricing')}`)
    return
  }
  try {
    const data = await createPayment(plan.id)
    // 跳转支付宝沙箱收银台
    window.location.href = data.pay_url
  } catch (err) {
    ElMessage.error(err.message || '下单失败')
  }
}

// 支付宝同步跳回（return_url）后：根据 out_trade_no 主动确认订单
onMounted(async () => {
  const orderId = route.query.out_trade_no
  if (!orderId) return
  try {
    const data = await queryPayment(orderId)
    if (data.order.status === 'paid') {
      ElMessage.success(`支付成功，已到账 ${data.order.credits} 次额度`)
      await fetchCurrentUser()
    } else {
      ElMessage.info('订单尚未完成支付，可在订单列表中查看')
    }
  } catch (err) {
    ElMessage.error(err.message || '订单查询失败')
  }
})
</script>

<style scoped>
.pricing-page__main {
  min-height: calc(100vh - 200px);
  padding: 120px 24px 80px;
  background: transparent;
}

.pricing-page__container {
  max-width: 1000px;
  margin: 0 auto;
}

.pricing-page__header {
  text-align: center;
  margin-bottom: 64px;
}

.pricing-page__title {
  font-size: 36px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 16px;
}

.pricing-page__desc {
  font-size: 18px;
  color: var(--text-secondary);
  margin: 0;
}

.pricing-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
  align-items: start;
}

.pricing-card {
  position: relative;
  background: var(--glass-surface);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-xl);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
  padding: 32px;
  transition: transform var(--transition-base), box-shadow var(--transition-base), background var(--transition-base);
}

.pricing-card:hover {
  transform: translateY(-4px);
  background: var(--glass-surface-hover);
  box-shadow: var(--glass-shadow-lg), var(--glass-highlight);
}

.pricing-card--featured {
  transform: scale(1.05);
  background: linear-gradient(160deg, rgba(99, 102, 241, 0.18), rgba(255, 255, 255, 0.28) 55%, rgba(255, 255, 255, 0.34));
  border: 1px solid var(--brand-500);
  box-shadow: 0 18px 52px rgba(79, 70, 229, 0.22), var(--glass-highlight);
}

.pricing-card--featured:hover {
  transform: scale(1.05) translateY(-4px);
  background: linear-gradient(160deg, rgba(99, 102, 241, 0.24), rgba(255, 255, 255, 0.36) 55%, rgba(255, 255, 255, 0.42));
  box-shadow: 0 22px 60px rgba(79, 70, 229, 0.26), var(--glass-highlight);
}

.pricing-card__badge {
  position: absolute;
  top: -12px;
  left: 50%;
  transform: translateX(-50%);
  padding: 6px 16px;
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  color: white;
  border-radius: 9999px;
  font-size: 12px;
  font-weight: 600;
  box-shadow: 0 6px 16px rgba(79, 70, 229, 0.32), inset 0 1px 0 rgba(255, 255, 255, 0.30);
}

.pricing-card__name {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.pricing-card__desc {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 0 0 24px;
}

.pricing-card__price {
  display: flex;
  align-items: baseline;
  gap: 4px;
  margin-bottom: 24px;
}

.pricing-card__currency {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
}

.pricing-card__amount {
  font-size: 48px;
  font-weight: 800;
  color: var(--text-primary);
}

.pricing-card__period {
  font-size: 14px;
  color: var(--text-secondary);
}

.pricing-card__features {
  list-style: none;
  padding: 0;
  margin: 0 0 32px;
}

.pricing-card__features li {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 0;
  font-size: 14px;
  color: var(--text-secondary);
  border-bottom: 1px solid rgba(148, 163, 184, 0.15);
}

.pricing-card__features li:last-child {
  border-bottom: none;
}

.pricing-card__features .el-icon {
  color: var(--success-500);
  flex-shrink: 0;
  margin-top: 2px;
}

.pricing-card__btn {
  width: 100%;
  height: 44px;
  border-radius: var(--radius-md);
  font-weight: 600;
}

.pricing-card--featured .pricing-card__btn {
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  border: none;
}

.faq-section {
  max-width: 720px;
  margin: 80px auto 0;
  padding: 32px;
  background: var(--glass-surface);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
}

.faq-section__title {
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
  text-align: center;
  margin: 0 0 32px;
}

.faq-section__list :deep(.el-collapse-item__header) {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  background: transparent;
}

.faq-section__list :deep(.el-collapse-item__content) {
  font-size: 14px;
  line-height: 1.8;
  color: var(--text-secondary);
  background: transparent;
}

@media (max-width: 900px) {
  .pricing-grid {
    grid-template-columns: 1fr;
  }

  .pricing-card--featured {
    transform: none;
  }
}
</style>

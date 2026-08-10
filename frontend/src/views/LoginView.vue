<template>
  <div class="auth-page">
    <AppNavbar />

    <main class="auth-page__main">
      <div class="auth-card">
        <div class="auth-card__header">
          <div class="auth-card__logo">
            <el-icon><Document /></el-icon>
          </div>
          <h1 class="auth-card__title">欢迎回来</h1>
          <p class="auth-card__desc">登录后继续处理你的文档</p>
        </div>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          class="auth-card__form"
          @keyup.enter="handleSubmit"
        >
          <el-form-item prop="email">
            <el-input
              v-model="form.email"
              placeholder="your@email.com"
              size="large"
              :prefix-icon="Message"
            />
          </el-form-item>

          <el-form-item prop="password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="请输入密码"
              size="large"
              show-password
              :prefix-icon="Lock"
            />
          </el-form-item>

          <div class="auth-card__options">
            <el-checkbox v-model="form.remember">记住我</el-checkbox>
            <a href="#" class="auth-card__link">忘记密码？</a>
          </div>

          <el-form-item>
            <el-button
              type="primary"
              size="large"
              class="auth-card__submit"
              :loading="loading"
              @click="handleSubmit"
            >
              登录
            </el-button>
          </el-form-item>
        </el-form>

        <p class="auth-card__footer">
          还没有账号？<router-link to="/register">立即注册</router-link>
        </p>
      </div>
    </main>

    <AppFooter />
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Document, Message, Lock } from '@element-plus/icons-vue'
import AppNavbar from '@/components/AppNavbar.vue'
import AppFooter from '@/components/AppFooter.vue'
import { login } from '@/api/auth.js'
import { useAuthStore } from '@/stores/auth.js'

const router = useRouter()
const { setAuth } = useAuthStore()

const formRef = ref(null)
const loading = ref(false)

const form = reactive({
  email: '',
  password: '',
  remember: false,
})

const rules = {
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '请输入有效的邮箱地址', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' },
  ],
}

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    const data = await login({
      email: form.email,
      password: form.password,
      remember: form.remember,
    })
    setAuth(data.token, data.user)
    ElMessage.success('登录成功')
    router.push(router.currentRoute.value.query.redirect || '/upload')
  } catch (err) {
    ElMessage.error(err.message || '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-page__main {
  min-height: calc(100vh - 200px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 120px 24px 80px;
  background: transparent;
}

.auth-card {
  width: 100%;
  max-width: 420px;
  padding: 40px;
  background: var(--glass-surface-strong);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-xl);
  box-shadow: var(--glass-shadow-lg), var(--glass-highlight);
}

.auth-card__header {
  text-align: center;
  margin-bottom: 32px;
}

.auth-card__logo {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  box-shadow: 0 8px 20px rgba(79, 70, 229, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.30);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 24px;
  margin: 0 auto 16px;
}

.auth-card__title {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.auth-card__desc {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 0;
}

.auth-card__form :deep(.el-input__inner) {
  border-radius: var(--radius-md);
  height: 44px;
}

.auth-card__options {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
}

.auth-card__link {
  font-size: 14px;
  color: var(--text-link);
}

.auth-card__submit {
  width: 100%;
  height: 44px;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  border: none;
  font-size: 15px;
  font-weight: 600;
}

.auth-card__divider {
  position: relative;
  text-align: center;
  margin: 24px 0;
}

.auth-card__divider::before {
  content: '';
  position: absolute;
  top: 50%;
  left: 0;
  right: 0;
  height: 1px;
  background: var(--border-color);
}

.auth-card__divider span {
  position: relative;
  padding: 0 16px;
  background: rgba(255, 255, 255, 0.32);
  font-size: 13px;
  color: var(--text-tertiary);
}

.auth-card__social {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 24px;
}

.auth-card__social-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  width: 100%;
  padding: 12px;
  background: rgba(255, 255, 255, 0.30);
  backdrop-filter: blur(12px) saturate(165%);
  -webkit-backdrop-filter: blur(12px) saturate(165%);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-md);
  font-size: 14px;
  color: var(--text-primary);
  cursor: pointer;
  transition: background var(--transition-fast), box-shadow var(--transition-fast);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.50);
}

.auth-card__social-btn:hover {
  background: rgba(255, 255, 255, 0.48);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
}

.auth-card__social-btn img {
  width: 18px;
  height: 18px;
}

.auth-card__footer {
  text-align: center;
  font-size: 14px;
  color: var(--text-secondary);
  margin: 0;
}
</style>

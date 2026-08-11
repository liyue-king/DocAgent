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
            <label
              class="auth-card__option"
              :class="{ 'auth-card__option--checked': form.remember }"
            >
              <input
                v-model="form.remember"
                type="checkbox"
                class="auth-card__option-input"
              />
              <span class="auth-card__option-box" aria-hidden="true">
                <el-icon v-if="form.remember" :size="12"><Check /></el-icon>
              </span>
              <span class="auth-card__option-text">记住我</span>
            </label>
            <a class="auth-card__link" @click.prevent="resetDialogVisible = true">忘记密码？</a>
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

    <el-dialog
      v-model="resetDialogVisible"
      title="重置密码"
      width="400px"
      destroy-on-close
      @closed="clearResetTimer"
    >
      <el-form ref="resetFormRef" :model="resetForm" :rules="resetRules" label-width="0">
        <el-form-item prop="email">
          <el-input
            v-model="resetForm.email"
            placeholder="注册邮箱"
            :prefix-icon="Message"
          />
        </el-form-item>
        <el-form-item prop="code">
          <div class="auth-card__code-row">
            <el-input v-model="resetForm.code" placeholder="邮箱验证码" maxlength="6" />
            <el-button :disabled="resetCountdown > 0" @click="handleSendResetCode">
              {{ resetCountdown > 0 ? `${resetCountdown}s` : '获取验证码' }}
            </el-button>
          </div>
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="resetForm.password"
            type="password"
            placeholder="新密码（6-64 位）"
            show-password
            :prefix-icon="Lock"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resetDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="resetSubmitting" @click="handleResetPassword">
          重置密码
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Check, Document, Lock, Message } from '@element-plus/icons-vue'
import AppNavbar from '@/components/AppNavbar.vue'
import AppFooter from '@/components/AppFooter.vue'
import { login, sendEmailCode, resetPassword } from '@/api/auth.js'
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

function clearResetTimer() {
  if (resetTimer) {
    clearInterval(resetTimer)
    resetTimer = null
    resetCountdown.value = 0
  }
}

const resetDialogVisible = ref(false)
const resetFormRef = ref(null)
const resetSubmitting = ref(false)
const resetCountdown = ref(0)
let resetTimer = null

const resetForm = reactive({ email: '', code: '', password: '' })
const resetRules = {
  email: [
    { required: true, message: '请输入注册邮箱', trigger: 'blur' },
    { type: 'email', message: '请输入有效的邮箱地址', trigger: 'blur' },
  ],
  code: [
    { required: true, message: '请输入验证码', trigger: 'blur' },
    { min: 6, max: 6, message: '验证码为 6 位数字', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, max: 64, message: '密码长度 6-64 位', trigger: 'blur' },
  ],
}

async function handleSendResetCode() {
  if (!resetForm.email) {
    ElMessage.warning('请先填写注册邮箱')
    return
  }
  try {
    const data = await sendEmailCode(resetForm.email)
    ElMessage.success(data.msg || '验证码已发送')
    resetCountdown.value = 60
    resetTimer = setInterval(() => {
      resetCountdown.value -= 1
      if (resetCountdown.value <= 0) clearInterval(resetTimer)
    }, 1000)
  } catch (err) {
    ElMessage.error(err.message || '验证码发送失败')
  }
}

async function handleResetPassword() {
  const valid = await resetFormRef.value?.validate().catch(() => false)
  if (!valid) return
  resetSubmitting.value = true
  try {
    const data = await resetPassword(resetForm.email, resetForm.code, resetForm.password)
    ElMessage.success(data.msg || '密码重置成功')
    resetDialogVisible.value = false
    form.email = resetForm.email
    form.password = ''
    resetForm.code = ''
    resetForm.password = ''
  } catch (err) {
    ElMessage.error(err.message || '密码重置失败')
  } finally {
    resetSubmitting.value = false
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

.auth-card__option {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
  -webkit-user-select: none;
  padding: 4px 6px 4px 2px;
  border-radius: 8px;
  transition: background var(--transition-fast);
}

.auth-card__option:hover {
  background: rgba(99, 102, 241, 0.08);
}

.auth-card__option-input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  pointer-events: none;
}

.auth-card__option-box {
  width: 16px;
  height: 16px;
  border-radius: 4px;
  border: 1px solid rgba(148, 163, 184, 0.50);
  background: rgba(255, 255, 255, 0.55);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: white;
  flex-shrink: 0;
  transition: all var(--transition-fast);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.60);
}

.auth-card__option--checked .auth-card__option-box {
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  border-color: var(--brand-600);
  box-shadow: 0 2px 8px rgba(79, 70, 229, 0.30);
}

.auth-card__option-text {
  font-size: 14px;
  color: var(--text-secondary);
}

.auth-card__code-row {
  display: flex;
  gap: 10px;
  width: 100%;
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

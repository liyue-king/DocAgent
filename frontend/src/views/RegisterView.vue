<template>
  <div class="auth-page">
    <AppNavbar />

    <main class="auth-page__main">
      <div class="auth-card">
        <div v-if="!registered" class="auth-card__content">
          <div class="auth-card__header">
            <div class="auth-card__logo">
              <el-icon><Document /></el-icon>
            </div>
            <h1 class="auth-card__title">创建账号</h1>
            <p class="auth-card__desc">开始免费体验 AI 文档排版</p>
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

            <el-form-item prop="code">
              <div class="auth-card__code-row">
                <el-input
                  v-model="form.code"
                  placeholder="6 位邮箱验证码"
                  size="large"
                  maxlength="6"
                  :prefix-icon="Message"
                  @keyup.enter="handleSubmit"
                />
                <el-button
                  class="auth-card__code-btn"
                  size="large"
                  :disabled="countdown > 0 || sendingCode"
                  @click="handleSendCode"
                >
                  {{ sendingCode ? '发送中...' : countdown > 0 ? `${countdown}s 后重发` : '发送验证码' }}
                </el-button>
              </div>
            </el-form-item>

            <el-form-item prop="password">
              <el-input
                v-model="form.password"
                type="password"
                placeholder="设置密码"
                size="large"
                show-password
                :prefix-icon="Lock"
                @input="checkStrength"
              />
            </el-form-item>

            <div class="auth-card__strength">
              <div class="auth-card__strength-bar">
                <div
                  class="auth-card__strength-fill"
                  :class="`auth-card__strength-fill--${strength}`"
                  :style="{ width: strengthWidth }"
                ></div>
              </div>
              <span class="auth-card__strength-text">密码强度：{{ strengthLabel }}</span>
            </div>

            <el-form-item prop="confirmPassword">
              <el-input
                v-model="form.confirmPassword"
                type="password"
                placeholder="确认密码"
                size="large"
                show-password
                :prefix-icon="Lock"
              />
            </el-form-item>

            <el-form-item prop="agreed">
              <label
                class="auth-card__option"
                :class="{ 'auth-card__option--checked': form.agreed }"
              >
                <input
                  v-model="form.agreed"
                  type="checkbox"
                  class="auth-card__option-input"
                  @change="handleAgreedChange"
                />
                <span class="auth-card__option-box" aria-hidden="true">
                  <el-icon v-if="form.agreed" :size="12"><Check /></el-icon>
                </span>
                <span class="auth-card__option-text">
                  我已阅读并同意
                  <a class="auth-card__agreement" href="#" @click.prevent.stop>《用户协议》</a>
                  和
                  <a class="auth-card__agreement" href="#" @click.prevent.stop>《隐私政策》</a>
                </span>
              </label>
            </el-form-item>

            <el-form-item>
              <el-button
                type="primary"
                size="large"
                class="auth-card__submit"
                :loading="loading"
                @click="handleSubmit"
              >
                注册
              </el-button>
            </el-form-item>
          </el-form>

          <p class="auth-card__footer">
            已有账号？<router-link to="/login">立即登录</router-link>
          </p>
        </div>

        <div v-else class="auth-card__success">
          <AnimatedCheck />
          <h2 class="auth-card__success-title">注册成功</h2>
          <p class="auth-card__success-desc">正在跳转...</p>
        </div>
      </div>
    </main>

    <AppFooter />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Check, Document, Lock, Message } from '@element-plus/icons-vue'
import AppNavbar from '@/components/AppNavbar.vue'
import AppFooter from '@/components/AppFooter.vue'
import AnimatedCheck from '@/components/AnimatedCheck.vue'
import { register, sendEmailCode } from '@/api/auth.js'
import { useAuthStore } from '@/stores/auth.js'

const router = useRouter()
const { setAuth } = useAuthStore()

const formRef = ref(null)
const loading = ref(false)
const registered = ref(false)
const strength = ref('weak')

const form = reactive({
  email: '',
  code: '',
  password: '',
  confirmPassword: '',
  agreed: false,
})
const countdown = ref(0)
const sendingCode = ref(false)
let countdownTimer = null

onUnmounted(() => {
  if (countdownTimer) clearInterval(countdownTimer)
})

const strengthLabel = computed(() => {
  const map = { weak: '弱', medium: '中', strong: '强' }
  return map[strength.value]
})

const strengthWidth = computed(() => {
  const map = { weak: '33%', medium: '66%', strong: '100%' }
  return map[strength.value]
})

const validateConfirmPassword = (rule, value, callback) => {
  if (value !== form.password) {
    callback(new Error('两次输入的密码不一致'))
  } else {
    callback()
  }
}

const rules = {
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '请输入有效的邮箱地址', trigger: 'blur' },
  ],
  code: [
    { required: true, message: '请输入验证码', trigger: 'blur' },
    { len: 6, message: '验证码为 6 位数字', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    { validator: validateConfirmPassword, trigger: 'blur' },
  ],
  agreed: [
    { type: 'boolean', required: true, message: '请同意用户协议', trigger: 'change' },
  ],
}

function startCountdown() {
  countdown.value = 60
  countdownTimer = setInterval(() => {
    countdown.value -= 1
    if (countdown.value <= 0) {
      clearInterval(countdownTimer)
      countdownTimer = null
    }
  }, 1000)
}

async function handleSendCode() {
  if (countdown.value > 0 || sendingCode.value) return
  const valid = await formRef.value?.validateField('email').catch(() => false)
  if (!valid) return
  sendingCode.value = true
  try {
    await sendEmailCode(form.email)
    ElMessage.success('验证码已发送，请查收邮件')
    startCountdown()
  } catch (err) {
    ElMessage.error(err.message || '验证码发送失败')
  } finally {
    sendingCode.value = false
  }
}

function checkStrength() {
  const pwd = form.password
  let score = 0
  if (pwd.length >= 6) score++
  if (pwd.length >= 10) score++
  if (/[A-Z]/.test(pwd)) score++
  if (/[0-9]/.test(pwd)) score++
  if (/[^A-Za-z0-9]/.test(pwd)) score++

  if (score <= 2) strength.value = 'weak'
  else if (score <= 4) strength.value = 'medium'
  else strength.value = 'strong'
}

function handleAgreedChange() {
  // 原生 checkbox 不触发 Element Plus 表单项校验，这里手动触发一次
  formRef.value?.validateField('agreed').catch(() => {})
}

async function handleSubmit() {
  if (!form.agreed) {
    ElMessage.warning('请先阅读并同意《用户协议》和《隐私政策》')
    return
  }
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    const data = await register({
      email: form.email,
      password: form.password,
      code: form.code,
    })
    setAuth(data.token, data.user)
    registered.value = true
    ElMessage.success('注册成功')
    setTimeout(() => router.push('/upload'), 1500)
  } catch (err) {
    ElMessage.error(err.message || '注册失败')
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

.auth-card__code-row {
  display: flex;
  gap: 10px;
  width: 100%;
}

.auth-card__option {
  display: inline-flex;
  align-items: flex-start;
  gap: 8px;
  cursor: pointer;
  user-select: none;
  -webkit-user-select: none;
  padding: 4px 6px 4px 2px;
  border-radius: 8px;
  transition: background var(--transition-fast);
  line-height: 1.5;
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
  margin-top: 1px;
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

.auth-card__agreement {
  color: var(--text-link);
  cursor: pointer;
  text-decoration: none;
}

.auth-card__agreement:hover {
  text-decoration: underline;
}

.auth-card__code-btn {
  flex-shrink: 0;
  min-width: 118px;
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.32);
  backdrop-filter: blur(10px) saturate(165%);
  -webkit-backdrop-filter: blur(10px) saturate(165%);
  border: 1px solid var(--glass-border);
  color: var(--text-primary);
  font-weight: 500;
}

.auth-card__code-btn:not(:disabled):hover {
  background: rgba(99, 102, 241, 0.14);
  color: var(--brand-600);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
}

.auth-card__strength {
  margin-bottom: 24px;
}

.auth-card__strength-bar {
  height: 4px;
  background: rgba(148, 163, 184, 0.2);
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: 6px;
}

.auth-card__strength-fill {
  height: 100%;
  border-radius: 2px;
  transition: width var(--transition-base), background var(--transition-base);
}

.auth-card__strength-fill--weak { background: var(--error-500); }
.auth-card__strength-fill--medium { background: var(--warning-500); }
.auth-card__strength-fill--strong { background: var(--success-500); }

.auth-card__strength-text {
  font-size: 12px;
  color: var(--text-secondary);
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

.auth-card__success {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 0;
  text-align: center;
}

.auth-card__success-title {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 24px 0 8px;
}

.auth-card__success-desc {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 0;
}
</style>

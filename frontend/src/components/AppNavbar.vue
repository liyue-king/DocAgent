<template>
  <header class="navbar" :class="{ 'navbar--scrolled': isScrolled }">
    <div class="navbar__container">
      <router-link to="/" class="navbar__brand">
        <div class="navbar__logo">
          <el-icon><Document /></el-icon>
        </div>
        <span class="navbar__title">DocAgent</span>
      </router-link>

      <nav class="navbar__links">
        <router-link to="/chat">AI 助手</router-link>
        <router-link to="/knowledge">知识库</router-link>
        <router-link v-if="isAdmin" to="/admin/knowledge">平台知识库</router-link>
        <router-link to="/templates">模板</router-link>
        <router-link to="/pricing">定价</router-link>
        <router-link to="/about">关于</router-link>
      </nav>

      <div class="navbar__actions">
        <template v-if="isLoggedIn">
          <router-link to="/history" class="navbar__link">历史任务</router-link>
          <span class="navbar__divider"></span>
          <el-dropdown>
            <span class="navbar__user">
              <el-avatar :size="32" :icon="UserFilled" />
              <span class="navbar__user-info">
                <span class="navbar__user-name">{{ user?.email || '用户' }}</span>
                <span class="navbar__user-credits">余额 {{ user?.credits_balance ?? 0 }} 次</span>
              </span>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item disabled>
                  余额：{{ user?.credits_balance ?? 0 }} 次
                </el-dropdown-item>
                <el-dropdown-item @click="handleLogout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
        <template v-else>
          <router-link to="/login" class="navbar__link">登录</router-link>
          <router-link to="/upload" class="navbar__cta">立即使用</router-link>
        </template>
      </div>
    </div>
  </header>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { Document, UserFilled } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth.js'

const router = useRouter()
const { isLoggedIn, isAdmin, user, clearAuth } = useAuthStore()

const isScrolled = ref(false)

function handleScroll() {
  isScrolled.value = window.scrollY > 10
}

function handleLogout() {
  clearAuth()
  router.push('/')
}

onMounted(() => {
  window.addEventListener('scroll', handleScroll)
})

onUnmounted(() => {
  window.removeEventListener('scroll', handleScroll)
})
</script>

<style scoped>
.navbar {
  position: fixed;
  top: 16px;
  left: 50%;
  transform: translateX(-50%);
  width: min(1180px, calc(100% - 32px));
  z-index: 100;
  padding: 0 20px;
  border-radius: 999px;
  background: var(--glass-surface-strong);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
  transition: background var(--transition-base), box-shadow var(--transition-base);
}

.navbar--scrolled {
  background: var(--glass-surface-hover);
  box-shadow: var(--glass-shadow-lg), var(--glass-highlight);
}

.navbar__container {
  max-width: 1180px;
  margin: 0 auto;
  padding: 12px 4px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.navbar__brand {
  display: flex;
  align-items: center;
  gap: 10px;
  text-decoration: none;
}

.navbar__logo {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 20px;
}

.navbar__title {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
}

.navbar__links {
  display: flex;
  gap: 32px;
}

.navbar__links a {
  color: var(--text-secondary);
  font-size: 15px;
  font-weight: 500;
  text-decoration: none;
  transition: color var(--transition-fast);
}

.navbar__links a:hover,
.navbar__links a.router-link-active {
  color: var(--text-primary);
}

.navbar__actions {
  display: flex;
  align-items: center;
  gap: 20px;
}

.navbar__link {
  color: var(--text-secondary);
  font-size: 15px;
  font-weight: 500;
  text-decoration: none;
  transition: color var(--transition-fast);
}

.navbar__link:hover {
  color: var(--text-primary);
}

.navbar__cta {
  padding: 9px 20px;
  border-radius: 999px;
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  color: white;
  font-size: 14px;
  font-weight: 600;
  text-decoration: none;
  transition: transform var(--transition-fast), box-shadow var(--transition-fast);
  box-shadow: 0 6px 18px rgba(79, 70, 229, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.32);
}

.navbar__cta:hover {
  transform: translateY(-1px);
  box-shadow: var(--shadow-md);
  text-decoration: none;
}

.navbar__divider {
  width: 1px;
  height: 20px;
  background: var(--border-color);
}

.navbar__user {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.navbar__user-name {
  font-size: 14px;
  color: var(--text-secondary);
}

.navbar__user-info {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  line-height: 1.25;
}

.navbar__user-credits {
  font-size: 12px;
  color: var(--text-tertiary);
}

@media (max-width: 960px) {
  .navbar__links {
    display: none;
  }
}

@media (max-width: 720px) {
  .navbar__user-name {
    display: none;
  }
}
</style>

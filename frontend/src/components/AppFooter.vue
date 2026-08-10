<template>
  <footer class="footer">
    <div class="footer__container">
      <div class="footer__links">
        <router-link to="/about">关于我们</router-link>
        <a href="#">隐私政策</a>
        <a href="#">服务条款</a>
        <a href="#">帮助中心</a>
      </div>
      <p class="footer__copyright">© 2024 DocAgent. 让文档更有力量。</p>
    </div>
  </footer>
</template>

<style scoped>
.footer {
  margin: 0 24px 32px;
  border-radius: 28px;
  background: var(--glass-surface);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
}

.footer__container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 32px 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}

.footer__links {
  display: flex;
  gap: 32px;
}

.footer__links a {
  color: var(--text-secondary);
  font-size: 14px;
  text-decoration: none;
  transition: color var(--transition-fast);
}

.footer__links a:hover {
  color: var(--text-primary);
}

.footer__copyright {
  color: var(--text-tertiary);
  font-size: 13px;
  margin: 0;
}
</style>

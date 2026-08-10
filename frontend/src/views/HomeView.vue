<template>
  <div class="home">
    <AppNavbar />

    <main class="home__main">
      <!-- Hero -->
      <section class="hero">
        <div class="hero__container">
          <div class="hero__content">
            <div class="hero__badge">
              <el-icon><MagicStick /></el-icon>
              <span>AI 驱动的文档排版</span>
            </div>
            <h1 class="hero__title">
              让文档自己<br />
              <span class="hero__title--highlight">学会排版</span>
            </h1>
            <p class="hero__desc">
              上传 Word 原始稿件，DocAgent AI 自动识别层级、优化版式、统一风格。让你的创作更专注，繁琐排版交给我们。
            </p>
            <div class="hero__actions">
              <router-link to="/upload" class="hero__cta">
                免费开始使用
              </router-link>
              <router-link to="/templates" class="hero__cta hero__cta--secondary">
                查看演示
              </router-link>
            </div>
            <div class="hero__stats">
              <div class="hero__stat">
                <strong>10,000+</strong>
                <span>用户通过 AI 节省了排版时间</span>
              </div>
            </div>
          </div>
          <div class="hero__visual">
            <DocumentMockup />
            <div class="hero__floating-card">
              <el-icon><Check /></el-icon>
              <span>AI 处理中...</span>
            </div>
          </div>
        </div>
      </section>

      <!-- Features -->
      <section class="features">
        <div class="features__container">
          <div class="features__header">
            <h2 class="features__title">AI 驱动的智能文档体验</h2>
            <p class="features__desc">通过高级深度学习模型，DocAgent 能理解文档结构并自动应用最佳样式。</p>
          </div>
          <div class="features__grid">
            <div class="feature-card">
              <div class="feature-card__icon">
                <el-icon><Upload /></el-icon>
              </div>
              <h3>一键上传</h3>
              <p>支持所有主流 Word 格式（docx/doc），无论是论文报告还是合同简历都能完美支持。</p>
            </div>
            <div class="feature-card">
              <div class="feature-card__icon">
                <el-icon><Cpu /></el-icon>
              </div>
              <h3>AI 语义识别</h3>
              <p>智能分析标题、正文、引用、列表等文档元素，根据内容逻辑自动套用排版规则。</p>
            </div>
            <div class="feature-card">
              <div class="feature-card__icon">
                <el-icon><Download /></el-icon>
              </div>
              <h3>即刻下载</h3>
              <p>生成的文档保留完整的可编辑性，样式表已为你配置完成，你可以随时进行二次编辑。</p>
            </div>
          </div>
        </div>
      </section>

      <!-- Showcase -->
      <section class="showcase">
        <div class="showcase__container">
          <div class="showcase__card">
            <div class="showcase__content">
              <span class="showcase__label">DESIGN AESTHETICS</span>
              <h2 class="showcase__title">极简主义排版</h2>
              <p class="showcase__desc">
                我们采用磨砂玻璃质感，营造晨曦般的通透视觉体验。每一个细节都经过 AI 深度学习，确保文档在专业感与设计感之间达到完美平衡。
              </p>
              <router-link to="/about" class="showcase__cta">
                了解更多详情
              </router-link>
            </div>
            <div class="showcase__image">
              <img src="https://images.unsplash.com/photo-1456324504439-367cee13d656?w=600&h=400&fit=crop" alt="文档排版示例" />
            </div>
          </div>
        </div>
      </section>

      <!-- CTA -->
      <section class="cta-section">
        <div class="cta-section__container">
          <h2 class="cta-section__title">准备好让文档焕然一新了吗？</h2>
          <p class="cta-section__desc">加入数千名先行者，体验前所未有的智能排版效率。</p>
          <div class="cta-section__actions">
            <router-link to="/upload" class="cta-section__btn">
              开始免费使用
            </router-link>
            <router-link to="/pricing" class="cta-section__btn cta-section__btn--secondary">
              联系销售团队
            </router-link>
          </div>
        </div>
      </section>
    </main>

    <AppFooter />
  </div>
</template>

<script setup>
import AppNavbar from '@/components/AppNavbar.vue'
import AppFooter from '@/components/AppFooter.vue'
import DocumentMockup from '@/components/DocumentMockup.vue'
import { MagicStick, Check, Upload, Cpu, Download } from '@element-plus/icons-vue'
</script>

<style scoped>
.home__main {
  padding-top: 72px;
}

.hero {
  padding: 80px 24px 100px;
  background: transparent;
  overflow: hidden;
  position: relative;
}

.hero::before {
  content: '';
  position: absolute;
  top: 10%;
  right: 5%;
  width: 400px;
  height: 400px;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.18) 0%, transparent 70%);
  border-radius: 50%;
  filter: blur(40px);
  pointer-events: none;
}

.hero::after {
  content: '';
  position: absolute;
  bottom: 5%;
  left: 0;
  width: 300px;
  height: 300px;
  background: radial-gradient(circle, rgba(16, 185, 129, 0.14) 0%, transparent 70%);
  border-radius: 50%;
  filter: blur(40px);
  pointer-events: none;
}

.hero__container {
  max-width: 1200px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 64px;
  align-items: center;
}

.hero__badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: var(--glass-surface-strong);
  backdrop-filter: var(--glass-blur-md);
  -webkit-backdrop-filter: var(--glass-blur-md);
  border: 1px solid var(--glass-border);
  border-radius: 9999px;
  font-size: 13px;
  color: var(--brand-600);
  font-weight: 500;
  margin-bottom: 24px;
  box-shadow: var(--glass-shadow), var(--glass-highlight);
}

.hero__title {
  font-size: 56px;
  line-height: 1.1;
  font-weight: 800;
  color: var(--text-primary);
  margin: 0 0 24px;
  letter-spacing: -0.02em;
}

.hero__title--highlight {
  background: linear-gradient(120deg, #6366F1 0%, #06B6D4 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.hero__desc {
  font-size: 18px;
  line-height: 1.7;
  color: var(--text-secondary);
  margin: 0 0 32px;
  max-width: 480px;
}

.hero__actions {
  display: flex;
  gap: 16px;
  margin-bottom: 40px;
}

.hero__cta {
  padding: 14px 28px;
  border-radius: var(--radius-md);
  font-size: 15px;
  font-weight: 600;
  text-decoration: none;
  transition: transform var(--transition-fast), box-shadow var(--transition-fast);
}

.hero__cta:hover {
  transform: translateY(-1px);
  text-decoration: none;
}

.hero__cta:first-child {
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  color: white;
  box-shadow: 0 10px 26px rgba(79, 70, 229, 0.30), inset 0 1px 0 rgba(255, 255, 255, 0.30);
}

.hero__cta--secondary {
  background: var(--glass-surface-strong);
  backdrop-filter: var(--glass-blur-md);
  -webkit-backdrop-filter: var(--glass-blur-md);
  color: var(--text-primary);
  border: 1px solid var(--glass-border);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
}

.hero__cta--secondary:hover {
  background: var(--glass-surface-hover);
}

.hero__stats {
  display: flex;
  gap: 32px;
}

.hero__stat strong {
  display: block;
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
}

.hero__stat span {
  font-size: 13px;
  color: var(--text-secondary);
}

.hero__visual {
  position: relative;
  display: flex;
  justify-content: center;
}

.hero__floating-card {
  position: absolute;
  bottom: 20px;
  right: 20px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 18px;
  background: var(--glass-surface-strong);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--glass-shadow-lg), var(--glass-highlight);
  font-size: 14px;
  color: var(--text-primary);
  animation: float 3s ease-in-out infinite;
}

.hero__floating-card .el-icon {
  color: var(--success-500);
}

@keyframes float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-8px); }
}

.features {
  padding: 96px 24px;
  background: transparent;
  position: relative;
}

.features::before {
  content: '';
  position: absolute;
  top: 20%;
  left: 50%;
  transform: translateX(-50%);
  width: 600px;
  height: 600px;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.10) 0%, transparent 60%);
  border-radius: 50%;
  filter: blur(60px);
  pointer-events: none;
}

.features__container {
  max-width: 1200px;
  margin: 0 auto;
}

.features__header {
  text-align: center;
  margin-bottom: 64px;
}

.features__title {
  font-size: 36px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 16px;
}

.features__desc {
  font-size: 18px;
  color: var(--text-secondary);
  margin: 0;
}

.features__grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
}

.feature-card {
  padding: 32px;
  background: var(--glass-surface);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
  transition: transform var(--transition-base), box-shadow var(--transition-base), background var(--transition-base);
}

.feature-card:hover {
  transform: translateY(-4px);
  background: var(--glass-surface-hover);
  box-shadow: var(--glass-shadow-lg), var(--glass-highlight);
}

.feature-card__icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.16), rgba(255, 255, 255, 0.34));
  border: 1px solid rgba(255, 255, 255, 0.48);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.50);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--brand-600);
  font-size: 24px;
  margin-bottom: 20px;
}

.feature-card h3 {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 12px;
}

.feature-card p {
  font-size: 15px;
  line-height: 1.7;
  color: var(--text-secondary);
  margin: 0;
}

.showcase {
  padding: 0 24px 120px;
  background: transparent;
}

.showcase__container {
  max-width: 1200px;
  margin: 0 auto;
}

.showcase__card {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 48px;
  align-items: center;
  padding: 48px;
  background: var(--glass-surface);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-xl);
  box-shadow: var(--glass-shadow-lg), var(--glass-highlight);
  overflow: hidden;
}

.showcase__label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.1em;
  color: var(--text-tertiary);
  margin-bottom: 12px;
}

.showcase__title {
  font-size: 32px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 16px;
}

.showcase__desc {
  font-size: 16px;
  line-height: 1.8;
  color: var(--text-secondary);
  margin: 0 0 24px;
}

.showcase__cta {
  display: inline-block;
  padding: 12px 24px;
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  color: white;
  border-radius: var(--radius-md);
  font-size: 14px;
  font-weight: 600;
  text-decoration: none;
}

.showcase__image {
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.showcase__image img {
  width: 100%;
  height: auto;
  display: block;
}

.cta-section {
  padding: 100px 24px;
  background: transparent;
  position: relative;
}

.cta-section::before {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 700px;
  height: 300px;
  background: radial-gradient(ellipse, rgba(99, 102, 241, 0.14) 0%, transparent 70%);
  filter: blur(50px);
  pointer-events: none;
}

.cta-section__container {
  max-width: 800px;
  margin: 0 auto;
  text-align: center;
}

.cta-section__title {
  font-size: 36px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 16px;
}

.cta-section__desc {
  font-size: 18px;
  color: var(--text-secondary);
  margin: 0 0 32px;
}

.cta-section__actions {
  display: flex;
  justify-content: center;
  gap: 16px;
}

.cta-section__btn {
  padding: 14px 28px;
  border-radius: var(--radius-md);
  font-size: 15px;
  font-weight: 600;
  text-decoration: none;
  transition: transform var(--transition-fast);
}

.cta-section__btn:hover {
  transform: translateY(-1px);
  text-decoration: none;
}

.cta-section__btn:first-child {
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  color: white;
}

.cta-section__btn--secondary {
  background: var(--glass-surface-strong);
  backdrop-filter: var(--glass-blur-md);
  -webkit-backdrop-filter: var(--glass-blur-md);
  color: var(--text-primary);
  border: 1px solid var(--glass-border);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
}

.cta-section__btn--secondary:hover {
  background: var(--glass-surface-hover);
}

@media (max-width: 900px) {
  .hero__container,
  .showcase__card {
    grid-template-columns: 1fr;
  }

  .features__grid {
    grid-template-columns: 1fr;
  }

  .hero__title {
    font-size: 40px;
  }
}
</style>

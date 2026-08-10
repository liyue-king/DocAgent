<template>
  <div class="about-page">
    <AppNavbar />

    <main class="about-page__main">
      <div class="about-page__container">
        <div class="about-page__hero">
          <h1 class="about-page__title">让 AI 重新定义文档排版</h1>
          <p class="about-page__desc">
            我们相信每个人都应该拥有专业、规范的文档，而不需要成为排版专家。DocAgent 通过多智能体协作，将繁琐的格式调整工作交给 AI，让你专注于内容本身。
          </p>
        </div>

        <div class="about-page__story">
          <div class="about-page__story-image">
            <img src="https://images.unsplash.com/photo-1522202176988-66273c2fd55f?w=600&h=400&fit=crop" alt="团队协作" />
          </div>
          <div class="about-page__story-content">
            <h2>产品故事</h2>
            <p>
              DocAgent 诞生于一个简单的观察：大多数人花费大量时间在调整字体、段落间距和标题层级上，而这些工作本可以由 AI 自动完成。我们构建了一个由 RAG 检索、Planner 规划、Executor 执行和 Validator 校验组成的多智能体系统，确保每一次排版都准确、一致、可信赖。
            </p>
          </div>
        </div>

        <div class="about-page__advantages">
          <h2 class="about-page__section-title">核心优势</h2>
          <div class="advantages-grid">
            <div class="advantage-card">
              <div class="advantage-card__icon">
                <el-icon><Share /></el-icon>
              </div>
              <h3>多智能体协作</h3>
              <p>四个专业 Agent 分工协作，从模板选择到质量校验，全流程自动化。</p>
            </div>
            <div class="advantage-card">
              <div class="advantage-card__icon">
                <el-icon><Search /></el-icon>
              </div>
              <h3>RAG 模板检索</h3>
              <p>基于语义理解和关键词匹配，智能推荐最适合的排版模板。</p>
            </div>
            <div class="advantage-card">
              <div class="advantage-card__icon">
                <el-icon><CircleCheck /></el-icon>
              </div>
              <h3>自动质量校验</h3>
              <p>处理完成后自动扫描字体、字号、行距等维度，确保排版达标。</p>
            </div>
          </div>
        </div>

        <div class="about-page__tech">
          <h2 class="about-page__section-title">技术栈</h2>
          <div class="tech-stack">
            <span class="tech-stack__item">Vue3</span>
            <span class="tech-stack__item">FastAPI</span>
            <span class="tech-stack__item">LangGraph</span>
            <span class="tech-stack__item">ChromaDB</span>
            <span class="tech-stack__item">Celery</span>
            <span class="tech-stack__item">MinIO</span>
          </div>
        </div>

        <div class="about-page__cta">
          <h2>准备好体验了吗？</h2>
          <p>加入数千名先行者，感受 AI 带来的排版效率提升。</p>
          <router-link to="/upload" class="about-page__cta-btn">免费开始</router-link>
        </div>
      </div>
    </main>

    <AppFooter />
  </div>
</template>

<script setup>
import { Share, Search, CircleCheck } from '@element-plus/icons-vue'
import AppNavbar from '@/components/AppNavbar.vue'
import AppFooter from '@/components/AppFooter.vue'
</script>

<style scoped>
.about-page__main {
  min-height: calc(100vh - 200px);
  padding: 120px 24px 80px;
  background: transparent;
}

.about-page__container {
  max-width: 900px;
  margin: 0 auto;
}

.about-page__hero {
  text-align: center;
  margin-bottom: 80px;
}

.about-page__title {
  font-size: 40px;
  font-weight: 800;
  color: var(--text-primary);
  margin: 0 0 20px;
}

.about-page__desc {
  font-size: 18px;
  line-height: 1.8;
  color: var(--text-secondary);
  margin: 0 auto;
  max-width: 680px;
}

.about-page__story {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 48px;
  align-items: center;
  margin-bottom: 80px;
  padding: 48px;
  background: var(--glass-surface);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-xl);
  box-shadow: var(--glass-shadow-lg), var(--glass-highlight);
}

.about-page__story-image {
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.about-page__story-image img {
  width: 100%;
  height: auto;
  display: block;
}

.about-page__story-content h2 {
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 16px;
}

.about-page__story-content p {
  font-size: 15px;
  line-height: 1.8;
  color: var(--text-secondary);
  margin: 0;
}

.about-page__section-title {
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
  text-align: center;
  margin: 0 0 40px;
}

.about-page__advantages {
  margin-bottom: 80px;
}

.advantages-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
}

.advantage-card {
  padding: 32px;
  background: var(--glass-surface);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
  transition: transform var(--transition-base), background var(--transition-base);
}

.advantage-card:hover {
  transform: translateY(-4px);
  background: var(--glass-surface-hover);
  box-shadow: var(--glass-shadow-lg), var(--glass-highlight);
}

.advantage-card__icon {
  width: 52px;
  height: 52px;
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

.advantage-card h3 {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 10px;
}

.advantage-card p {
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-secondary);
  margin: 0;
}

.about-page__tech {
  margin-bottom: 80px;
}

.tech-stack {
  display: flex;
  justify-content: center;
  gap: 16px;
  flex-wrap: wrap;
}

.tech-stack__item {
  padding: 10px 20px;
  background: var(--glass-surface);
  backdrop-filter: var(--glass-blur-md);
  -webkit-backdrop-filter: var(--glass-blur-md);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-md);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
  font-size: 14px;
  font-weight: 500;
  color: var(--text-secondary);
}

.about-page__cta {
  text-align: center;
  padding: 64px;
  background: var(--glass-surface);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-xl);
  box-shadow: var(--glass-shadow-lg), var(--glass-highlight);
}

.about-page__cta h2 {
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 12px;
}

.about-page__cta p {
  font-size: 16px;
  color: var(--text-secondary);
  margin: 0 0 24px;
}

.about-page__cta-btn {
  display: inline-block;
  padding: 14px 32px;
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  color: white;
  border-radius: 999px;
  font-size: 15px;
  font-weight: 600;
  text-decoration: none;
  transition: transform var(--transition-fast);
  box-shadow: 0 10px 26px rgba(79, 70, 229, 0.30), inset 0 1px 0 rgba(255, 255, 255, 0.30);
}

.about-page__cta-btn:hover {
  transform: translateY(-1px);
  text-decoration: none;
}

@media (max-width: 900px) {
  .about-page__story,
  .advantages-grid {
    grid-template-columns: 1fr;
  }
}
</style>

<template>
  <div class="templates-page">
    <AppNavbar />

    <main class="templates-page__main">
      <div class="templates-page__container">
        <div class="templates-page__header">
          <h1 class="templates-page__title">选择一个排版模板</h1>
          <p class="templates-page__desc">DocAgent 会根据你的文档内容智能推荐最合适的模板</p>
        </div>

        <!-- 智能推荐：用户输入 → RAG 匹配 -->
        <div class="template-card template-card--featured">
          <div class="template-card__content">
            <div class="template-card__badge">智能推荐</div>
            <h2 class="template-card__name">描述你的行业和文档类型</h2>
            <p class="template-card__desc">例如：教育行业的本科毕业论文 / 律师事务所的合同模板 / 政府单位的红头文件</p>
            <div class="template-card__input">
              <el-input
                v-model="query"
                placeholder="输入行业和文档类型，回车或点击开始推荐"
                maxlength="200"
                size="large"
                :disabled="recommending"
                @keyup.enter="recommend"
              />
              <el-button
                type="primary"
                size="large"
                class="template-card__btn"
                :loading="recommending"
                :disabled="!query.trim()"
                @click="recommend"
              >
                {{ recommending ? '匹配中...' : '开始推荐' }}
              </el-button>
            </div>
          </div>
          <div class="template-card__visual">
            <DocumentMockup />
          </div>
        </div>

        <!-- 推荐结果（RAG 推送） -->
        <div v-if="recommendations.length" class="recommend-results">
          <div class="recommend-results__header">
            <h3>为你推荐的模板</h3>
            <span class="recommend-results__hint">根据「{{ lastQuery }}」匹配</span>
          </div>
          <div class="recommend-results__grid">
            <div
              v-for="(r, idx) in recommendations"
              :key="r.template_name + idx"
              class="template-card recommend-card"
              :class="{ 'recommend-card--top': idx === 0 }"
            >
              <div v-if="idx === 0" class="template-card__badge">最匹配</div>
              <div class="recommend-card__head">
                <h3 class="template-card__name">{{ r.template_name }}</h3>
                <span class="recommend-card__category">{{ r.category || '未分类' }}</span>
              </div>
              <div class="recommend-card__score">
                <span class="recommend-card__score-num">{{ Math.round(r.score * 100) }}%</span>
                <el-progress
                  :percentage="Math.round(r.score * 100)"
                  :stroke-width="6"
                  color="#4F46E5"
                />
              </div>
              <p class="template-card__desc recommend-card__desc">{{ r.description }}</p>
              <el-button
                type="primary"
                class="recommend-card__use"
                @click="useRecommended(r)"
              >
                使用此模板
              </el-button>
            </div>
          </div>
        </div>

        <!-- 模板网格 -->
        <div class="templates-grid">
          <div
            v-for="template in templates"
            :key="template.id"
            class="template-card"
            :class="{ 'template-card--active': selected === template.id }"
            @click="selected = template.id"
          >
            <div class="template-card__icon">
              <el-icon :size="28"><component :is="template.icon" /></el-icon>
            </div>
            <h3 class="template-card__name">{{ template.name }}</h3>
            <p class="template-card__desc">{{ template.description }}</p>
            <div class="template-card__tags">
              <span v-for="tag in template.tags" :key="tag" class="template-card__tag">{{ tag }}</span>
            </div>
          </div>
        </div>

        <div class="templates-page__actions">
          <el-button type="primary" size="large" class="templates-page__submit" @click="useTemplate">
            使用选中模板
          </el-button>
        </div>
      </div>
    </main>

    <AppFooter />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { DocumentCopy, OfficeBuilding, FolderOpened, User, Reading, Files } from '@element-plus/icons-vue'
import AppNavbar from '@/components/AppNavbar.vue'
import AppFooter from '@/components/AppFooter.vue'
import DocumentMockup from '@/components/DocumentMockup.vue'
import { getTemplates, recommendTemplates } from '@/api/templates.js'

const router = useRouter()
const selected = ref(1)
const query = ref('')
const recommending = ref(false)
const recommendations = ref([])
const lastQuery = ref('')

const iconMap = {
  Reading,
  OfficeBuilding,
  FolderOpened,
  User,
  Files,
  DocumentCopy,
}

const fallbackTemplates = [
  { id: 1, name: '学术论文', description: '标题黑体三号，正文宋体小四，1.5倍行距，适用于毕业论文', icon: iconMap.Reading, tags: ['最常用'] },
  { id: 2, name: '商务报告', description: '简洁专业的商务排版，统一标题层级和段落间距', icon: iconMap.OfficeBuilding, tags: ['商务'] },
  { id: 3, name: '政府公文', description: '符合 GB/T 格式规范，仿宋三号，行距28磅', icon: iconMap.FolderOpened, tags: ['规范'] },
  { id: 4, name: '个人简历', description: '清晰简洁的简历排版，突出重点信息', icon: iconMap.User, tags: ['求职'] },
  { id: 5, name: '合同协议', description: '条款清晰的合同排版，自动编号和缩进', icon: iconMap.Files, tags: ['法律'] },
  { id: 6, name: '通用文档', description: '标准宋体黑体组合，适合日常办公文档', icon: iconMap.DocumentCopy, tags: ['通用'] },
]

const templates = ref(fallbackTemplates)

// 后端模板列表没有图标/标签字段，按名称匹配静态展示数据
function enrichTemplates(list) {
  return list.map((t) => {
    const known = fallbackTemplates.find((f) => f.name === t.name)
    const tags = known?.tags || (t.usage_count ? [`已用 ${t.usage_count} 次`] : ['官方模板'])
    return {
      id: t.id,
      name: t.name,
      description: t.description || known?.description || '通用排版模板',
      icon: known?.icon || DocumentCopy,
      tags,
    }
  })
}

onMounted(async () => {
  try {
    const data = await getTemplates()
    if (data.templates && data.templates.length) {
      templates.value = enrichTemplates(data.templates)
      selected.value = templates.value[0]?.id
    }
  } catch {
    // 后端不可用时保留静态模板列表
  }
})

async function recommend() {
  const text = query.value.trim()
  if (!text || recommending.value) return
  recommending.value = true
  try {
    const data = await recommendTemplates(text, 3)
    recommendations.value = data.recommendations || []
    lastQuery.value = text
    if (!recommendations.value.length) {
      ElMessage.warning('没有匹配到模板，换个描述试试')
    }
  } catch (err) {
    ElMessage.error(err.message || '推荐失败，请稍后再试')
  } finally {
    recommending.value = false
  }
}

function useRecommended(r) {
  ElMessage.success(`已推荐「${r.template_name}」，前往上传页应用`)
  router.push({ path: '/upload', query: { template: r.template_name } })
}

function useTemplate() {
  ElMessage.success('已选择模板')
  router.push('/upload')
}
</script>

<style scoped>
.templates-page__main {
  min-height: calc(100vh - 200px);
  padding: 120px 24px 80px;
  background: transparent;
}

.templates-page__container {
  max-width: 1000px;
  margin: 0 auto;
}

.templates-page__header {
  text-align: center;
  margin-bottom: 48px;
}

.templates-page__title {
  font-size: 32px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.templates-page__desc {
  font-size: 16px;
  color: var(--text-secondary);
  margin: 0;
}

.template-card {
  background: var(--glass-surface);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
  padding: 28px;
  transition: transform var(--transition-base), box-shadow var(--transition-base), border-color var(--transition-base), background var(--transition-base);
  cursor: pointer;
}

.template-card:hover {
  transform: translateY(-4px);
  background: var(--glass-surface-hover);
  box-shadow: var(--glass-shadow-lg), var(--glass-highlight);
}

.template-card--active {
  transform: translateY(-4px);
  background: var(--glass-surface-hover);
  box-shadow: 0 0 0 1px var(--brand-500), var(--glass-shadow-lg), var(--glass-highlight);
  border-color: var(--brand-500);
}

.template-card--featured {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 32px;
  align-items: center;
  margin-bottom: 24px;
  cursor: default;
  background: var(--glass-surface-strong);
}

.template-card--featured:hover {
  transform: none;
  border-color: var(--glass-border);
}

.template-card__badge {
  display: inline-block;
  padding: 4px 10px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.18), rgba(255, 255, 255, 0.30));
  backdrop-filter: blur(8px) saturate(160%);
  -webkit-backdrop-filter: blur(8px) saturate(160%);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.40);
  color: var(--brand-600);
  border-radius: 9999px;
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 12px;
}

.template-card__icon {
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
  margin-bottom: 16px;
}

.template-card__name {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.template-card__desc {
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-secondary);
  margin: 0 0 16px;
}

.template-card__meta {
  margin-bottom: 20px;
}

.template-card__confidence {
  display: block;
  font-size: 13px;
  color: var(--brand-500);
  font-weight: 600;
  margin-bottom: 8px;
}

.template-card__btn {
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  border: none;
}

.template-card__input {
  display: flex;
  gap: 12px;
}

.template-card__input :deep(.el-input__inner) {
  border-radius: var(--radius-md);
  height: 44px;
}

.recommend-results {
  margin-bottom: 32px;
}

.recommend-results__header {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 16px;
}

.recommend-results__header h3 {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}

.recommend-results__hint {
  font-size: 13px;
  color: var(--text-tertiary);
}

.recommend-results__grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
}

.recommend-card {
  position: relative;
  cursor: default;
}

.recommend-card--top {
  border-color: var(--brand-500);
  box-shadow: 0 0 0 1px var(--brand-500), var(--glass-shadow-lg), var(--glass-highlight);
}

.recommend-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.recommend-card__category {
  flex-shrink: 0;
  padding: 3px 10px;
  background: rgba(99, 102, 241, 0.12);
  border: 1px solid rgba(99, 102, 241, 0.24);
  border-radius: 9999px;
  font-size: 12px;
  color: var(--brand-600);
}

.recommend-card__score {
  margin-bottom: 14px;
}

.recommend-card__score-num {
  display: block;
  font-size: 13px;
  font-weight: 700;
  color: var(--brand-500);
  margin-bottom: 6px;
}

.recommend-card__desc {
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.recommend-card__use {
  width: 100%;
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  border: none;
  font-weight: 600;
}

.template-card__tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.template-card__tag {
  padding: 4px 10px;
  background: rgba(255, 255, 255, 0.32);
  border: 1px solid var(--glass-border);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.40);
  border-radius: 9999px;
  font-size: 12px;
  color: var(--text-secondary);
}

.template-card__visual {
  display: flex;
  justify-content: center;
}

.templates-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
}

.templates-page__actions {
  text-align: center;
  margin-top: 40px;
}

.templates-page__submit {
  width: 240px;
  height: 48px;
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  border: none;
  font-size: 15px;
  font-weight: 600;
}

@media (max-width: 900px) {
  .template-card__input {
    flex-direction: column;
  }

  .recommend-results__grid {
    grid-template-columns: 1fr;
  }

  .template-card--featured,
  .templates-grid {
    grid-template-columns: 1fr;
  }
}
</style>

<template>
  <div class="history-page">
    <AppNavbar />

    <main class="history-page__main">
      <div class="history-page__container">
        <div class="history-page__header">
          <div>
            <h1 class="history-page__title">我的任务</h1>
            <p class="history-page__desc">查看和管理你的文档排版任务</p>
          </div>
          <router-link to="/upload" class="history-page__new">
            新建任务
          </router-link>
        </div>

        <div class="history-page__filters">
          <el-input
            v-model="searchQuery"
            placeholder="搜索文件名"
            clearable
            :prefix-icon="Search"
            class="history-page__search"
          />
          <div class="history-page__status-tabs">
            <button
              v-for="tab in statusTabs"
              :key="tab.value"
              class="history-page__tab"
              :class="{ 'history-page__tab--active': activeTab === tab.value }"
              @click="activeTab = tab.value"
            >
              {{ tab.label }}
            </button>
          </div>
        </div>

        <div class="history-card">
          <el-table
            v-if="filteredTasks.length > 0"
            :data="filteredTasks"
            style="width: 100%"
            :header-cell-style="{ background: 'rgba(255, 255, 255, 0.24)', color: '#374151', fontWeight: 600 }"
          >
            <el-table-column prop="fileName" label="文件名" min-width="200">
              <template #default="{ row }">
                <div class="history-page__file">
                  <el-icon><Document /></el-icon>
                  <span>{{ row.fileName }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="createdAt" label="提交时间" width="160" />
            <el-table-column prop="template" label="使用模板" width="140" />
            <el-table-column prop="status" label="状态" width="120">
              <template #default="{ row }">
                <StatusTag :status="row.status" />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="160" fixed="right">
              <template #default="{ row }">
                <a
                  v-if="row.status === 'success'"
                  :href="`/api/v1/download/${row.id}`"
                  class="history-page__download"
                >
                  下载
                </a>
                <el-button v-else text @click="viewTask(row)">查看</el-button>
              </template>
            </el-table-column>
          </el-table>

          <EmptyState
            v-else
            title="还没有任务"
            description="去上传一个文档，体验 AI 智能排版"
          >
            <template #icon>
              <el-icon :size="48"><Document /></el-icon>
            </template>
            <template #action>
              <router-link to="/upload" class="history-page__new">
                上传文档
              </router-link>
            </template>
          </EmptyState>
        </div>
      </div>
    </main>

    <AppFooter />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Search, Document } from '@element-plus/icons-vue'
import AppNavbar from '@/components/AppNavbar.vue'
import AppFooter from '@/components/AppFooter.vue'
import StatusTag from '@/components/StatusTag.vue'
import EmptyState from '@/components/EmptyState.vue'
import { getTasks } from '@/api/tasks.js'

const router = useRouter()
const searchQuery = ref('')
const activeTab = ref('all')
const loading = ref(false)

const statusTabs = [
  { label: '全部', value: 'all' },
  { label: '处理中', value: 'processing' },
  { label: '成功', value: 'success' },
  { label: '失败', value: 'failed' },
]

const tasks = ref([])

async function loadTasks() {
  loading.value = true
  try {
    const data = await getTasks()
    tasks.value = (data.tasks || []).map((t) => ({
      id: t.id,
      fileName: t.input_file_name,
      createdAt: (t.created_at || '').replace('T', ' ').slice(0, 16),
      template: '—',
      status: t.status,
    }))
  } catch (err) {
    ElMessage.error(err.message || '任务加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(loadTasks)

const filteredTasks = computed(() => {
  let result = tasks.value

  if (activeTab.value === 'processing') {
    result = result.filter((t) => ['pending', 'retrieving', 'planning', 'executing', 'validating', 'retrying'].includes(t.status))
  } else if (activeTab.value === 'failed') {
    result = result.filter((t) => ['failed', 'expired'].includes(t.status))
  } else if (activeTab.value !== 'all') {
    result = result.filter((t) => t.status === activeTab.value)
  }

  if (searchQuery.value) {
    result = result.filter((t) => t.fileName.toLowerCase().includes(searchQuery.value.toLowerCase()))
  }

  return result
})

function viewTask(row) {
  router.push(`/task/${row.id}`)
}

</script>

<style scoped>
.history-page__main {
  min-height: calc(100vh - 200px);
  padding: 120px 24px 80px;
  background: transparent;
}

.history-page__container {
  max-width: 1000px;
  margin: 0 auto;
}

.history-page__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 32px;
}

.history-page__title {
  font-size: 32px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.history-page__desc {
  font-size: 16px;
  color: var(--text-secondary);
  margin: 0;
}

.history-page__new {
  padding: 12px 24px;
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  color: white;
  border-radius: 999px;
  font-size: 14px;
  font-weight: 600;
  text-decoration: none;
  box-shadow: 0 8px 20px rgba(79, 70, 229, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.30);
}

.history-page__filters {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;
}

.history-page__search {
  width: 280px;
}

.history-page__search :deep(.el-input__inner) {
  border-radius: var(--radius-md);
}

.history-page__status-tabs {
  display: flex;
  gap: 8px;
}

.history-page__tab {
  padding: 8px 16px;
  background: rgba(255, 255, 255, 0.30);
  backdrop-filter: blur(12px) saturate(165%);
  -webkit-backdrop-filter: blur(12px) saturate(165%);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-md);
  font-size: 14px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.45);
}

.history-page__tab:hover {
  color: var(--brand-600);
  border-color: var(--brand-500);
  background: rgba(255, 255, 255, 0.46);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
}

.history-page__tab--active {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.24), rgba(255, 255, 255, 0.30));
  color: var(--brand-700);
  border-color: var(--brand-500);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.40), 0 4px 14px rgba(99, 102, 241, 0.18);
}

.history-card {
  background: var(--glass-surface);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
  overflow: hidden;
}

.history-page__file {
  display: flex;
  align-items: center;
  gap: 8px;
}

.history-page__file .el-icon {
  color: var(--brand-500);
}

.history-page__download {
  color: var(--brand-600);
  font-size: 14px;
  font-weight: 500;
  text-decoration: none;
}

.history-page__download:hover {
  color: var(--brand-700);
  text-decoration: underline;
}

@media (max-width: 768px) {
  .history-page__header,
  .history-page__filters {
    flex-direction: column;
    align-items: flex-start;
  }

  .history-page__search {
    width: 100%;
  }
}
</style>

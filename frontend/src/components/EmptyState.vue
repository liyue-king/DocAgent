<template>
  <div class="empty-state">
    <div class="empty-state__icon">
      <slot name="icon">
        <el-icon :size="48"><Document /></el-icon>
      </slot>
    </div>
    <h3 class="empty-state__title">{{ title }}</h3>
    <p class="empty-state__desc">{{ description }}</p>
    <div v-if="$slots.action" class="empty-state__action">
      <slot name="action"></slot>
    </div>
  </div>
</template>

<script setup>
import { Document } from '@element-plus/icons-vue'

defineProps({
  title: {
    type: String,
    default: '暂无数据',
  },
  description: {
    type: String,
    default: '',
  },
})
</script>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 64px 24px;
  text-align: center;
}

.empty-state__icon {
  width: 80px;
  height: 80px;
  border-radius: 20px;
  background: var(--glass-surface);
  backdrop-filter: var(--glass-blur-md);
  -webkit-backdrop-filter: var(--glass-blur-md);
  border: 1px solid var(--glass-border);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-tertiary);
  margin-bottom: 20px;
}

.empty-state__title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.empty-state__desc {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 0 0 20px;
  max-width: 320px;
}

.empty-state__action {
  margin-top: 8px;
}
</style>

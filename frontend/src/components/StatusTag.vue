<template>
  <span class="status-tag" :class="`status-tag--${status}`">
    <span v-if="status === 'processing' || status === 'retrieving' || status === 'planning' || status === 'executing' || status === 'validating'" class="status-tag__dot status-tag__dot--pulse"></span>
    <span v-else class="status-tag__dot"></span>
    {{ label }}
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  status: {
    type: String,
    required: true,
  },
})

const labelMap = {
  pending: '等待中',
  retrieving: '检索中',
  planning: '规划中',
  executing: '执行中',
  validating: '校验中',
  retrying: '重试中',
  success: '成功',
  failed: '失败',
  expired: '已过期',
}

const label = computed(() => labelMap[props.status] || props.status)
</script>

<style scoped>
.status-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 9999px;
  font-size: 13px;
  font-weight: 500;
  border: 1px solid rgba(255, 255, 255, 0.30);
  backdrop-filter: blur(10px) saturate(160%);
  -webkit-backdrop-filter: blur(10px) saturate(160%);
}

.status-tag__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.status-tag--pending {
  background: rgba(148, 163, 184, 0.12);
  color: #64748B;
}

.status-tag--retrieving,
.status-tag--planning,
.status-tag--executing,
.status-tag--validating,
.status-tag--processing {
  background: rgba(99, 102, 241, 0.12);
  border-color: rgba(99, 102, 241, 0.18);
  color: var(--brand-600);
}

.status-tag--retrying {
  background: rgba(245, 158, 11, 0.12);
  border-color: rgba(245, 158, 11, 0.18);
  color: #B45309;
}

.status-tag--success {
  background: rgba(16, 185, 129, 0.12);
  border-color: rgba(16, 185, 129, 0.18);
  color: #059669;
}

.status-tag--failed {
  background: rgba(239, 68, 68, 0.12);
  border-color: rgba(239, 68, 68, 0.18);
  color: #DC2626;
}

.status-tag--expired {
  background: rgba(148, 163, 184, 0.12);
  color: #9CA3AF;
}

.status-tag__dot--pulse {
  animation: pulse 1.5s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
</style>

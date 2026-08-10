<template>
  <div class="progress-bar" :class="{ 'progress-bar--retrying': isRetrying }">
    <div class="progress-bar__segments">
      <div
        v-for="(segment, index) in segments"
        :key="index"
        class="progress-bar__segment"
        :class="{
          'progress-bar__segment--completed': segment.completed,
          'progress-bar__segment--active': segment.active,
        }"
      >
        <div class="progress-bar__fill" :style="{ width: segment.fillWidth }"></div>
        <span class="progress-bar__label">{{ segment.label }}</span>
      </div>
    </div>
    <div class="progress-bar__info">
      <span class="progress-bar__percent">{{ progress }}%</span>
      <span class="progress-bar__step">{{ step }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  progress: {
    type: Number,
    default: 0,
  },
  step: {
    type: String,
    default: '',
  },
  isRetrying: {
    type: Boolean,
    default: false,
  },
})

const segments = computed(() => {
  const items = [
    { label: 'RAG 检索', range: [0, 30] },
    { label: 'AI 规划', range: [30, 60] },
    { label: '文档修改', range: [60, 90] },
    { label: '质量校验', range: [90, 100] },
  ]

  return items.map((item) => {
    const [start, end] = item.range
    const completed = props.progress >= end
    const active = props.progress >= start && props.progress < end
    let fillWidth = '0%'

    if (completed) {
      fillWidth = '100%'
    } else if (active) {
      fillWidth = `${((props.progress - start) / (end - start)) * 100}%`
    }

    return {
      ...item,
      completed,
      active,
      fillWidth,
    }
  })
})
</script>

<style scoped>
.progress-bar {
  width: 100%;
}

.progress-bar__segments {
  display: flex;
  gap: 6px;
  margin-bottom: 12px;
}

.progress-bar__segment {
  flex: 1;
  height: 8px;
  background: rgba(148, 163, 184, 0.22);
  box-shadow: inset 0 1px 2px rgba(31, 38, 135, 0.08);
  border-radius: 4px;
  overflow: hidden;
  position: relative;
}

.progress-bar__fill {
  height: 100%;
  background: linear-gradient(90deg, var(--brand-500), var(--brand-600));
  box-shadow: 0 2px 8px rgba(79, 70, 229, 0.35);
  border-radius: 4px;
  transition: width 0.4s ease;
}

.progress-bar__segment--completed .progress-bar__fill {
  background: var(--success-500);
}

.progress-bar--retrying .progress-bar__segment--active .progress-bar__fill {
  background: linear-gradient(90deg, #F59E0B, #FBBF24);
  animation: breathe 0.8s ease-in-out infinite;
}

.progress-bar__label {
  display: block;
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-secondary);
  text-align: center;
}

.progress-bar__segment--active .progress-bar__label {
  color: var(--text-primary);
  font-weight: 600;
}

.progress-bar__info {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.progress-bar__percent {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
}

.progress-bar__step {
  font-size: 14px;
  color: var(--text-secondary);
}

.progress-bar--retrying .progress-bar__percent {
  color: #B45309;
}

@keyframes breathe {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}
</style>

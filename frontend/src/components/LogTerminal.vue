<template>
  <div class="log-terminal">
    <div class="log-terminal__header">
      <span class="log-terminal__dot log-terminal__dot--red"></span>
      <span class="log-terminal__dot log-terminal__dot--yellow"></span>
      <span class="log-terminal__dot log-terminal__dot--green"></span>
      <span class="log-terminal__title">Agent 日志</span>
    </div>
    <div ref="terminalRef" class="log-terminal__body">
      <div
        v-for="(log, index) in logs"
        :key="index"
        class="log-terminal__line"
      >
        <span v-if="log.time" class="log-terminal__time">{{ log.time }}</span>
        <span :class="['log-terminal__level', `log-terminal__level--${log.level || 'info'}`]">{{ (log.level || 'INFO').toUpperCase() }}</span>
        <span class="log-terminal__message">{{ log.message }}</span>
      </div>
      <div v-if="logs.length === 0" class="log-terminal__empty">
        等待任务开始...
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'

const props = defineProps({
  logs: {
    type: Array,
    default: () => [],
  },
})

const terminalRef = ref(null)

function scrollToBottom() {
  nextTick(() => {
    if (terminalRef.value) {
      terminalRef.value.scrollTop = terminalRef.value.scrollHeight
    }
  })
}

watch(() => props.logs.length, scrollToBottom, { immediate: true })
</script>

<style scoped>
.log-terminal {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.52) 0%, rgba(15, 23, 42, 0.74) 100%);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: var(--glass-shadow), inset 0 1px 0 rgba(255, 255, 255, 0.12);
}

.log-terminal__header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: rgba(255, 255, 255, 0.05);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.log-terminal__dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.log-terminal__dot--red { background: #FF5F57; }
.log-terminal__dot--yellow { background: #FFBD2E; }
.log-terminal__dot--green { background: #28C840; }

.log-terminal__title {
  margin-left: 8px;
  font-size: 12px;
  color: #94A3B8;
  font-family: var(--font-mono);
}

.log-terminal__body {
  height: 220px;
  padding: 16px;
  overflow-y: auto;
  font-family: var(--font-mono);
  font-size: 13px;
  line-height: 1.7;
}

.log-terminal__line {
  display: flex;
  gap: 12px;
  animation: slideIn 0.15s ease;
}

.log-terminal__time {
  color: #64748B;
  flex-shrink: 0;
}

.log-terminal__level {
  flex-shrink: 0;
  font-weight: 600;
  width: 48px;
}

.log-terminal__level--info { color: #34D399; }
.log-terminal__level--warning { color: #FBBF24; }
.log-terminal__level--error { color: #F87171; }

.log-terminal__message {
  color: #E2E8F0;
  word-break: break-all;
}

.log-terminal__empty {
  color: #64748B;
  text-align: center;
  padding-top: 80px;
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>

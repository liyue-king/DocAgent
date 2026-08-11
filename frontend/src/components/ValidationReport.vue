<template>
  <div v-if="report" class="report">
    <div class="report__header">
      <span class="report__title">样式覆盖率</span>
      <span
        class="report__coverage"
        :class="{ 'is-pass': report.passed, 'is-fail': !report.passed }"
      >
        {{ Math.round(report.coverage * 100) }}%
      </span>
    </div>
    <p class="report__meta">
      已匹配 {{ report.matched }} / {{ report.total }} 个可评估段落
    </p>
    <el-collapse v-if="missedList.length" class="report__missed">
      <el-collapse-item :title="`未匹配段落明细（${missedList.length} 处）`">
        <div v-for="(item, i) in missedList" :key="i" class="missed-item">
          <div class="missed-item__head">
            <span class="missed-item__tag">#{{ item.para_id }} · {{ item.style }}</span>
            <span class="missed-item__text">{{ item.text_preview || '（无文字预览）' }}</span>
          </div>
          <table class="missed-item__table">
            <tr v-for="(row, j) in dimRows(item)" :key="j">
              <td class="missed-item__dim">{{ row.label }}</td>
              <td class="missed-item__cell">期望：<b>{{ row.expected }}</b></td>
              <td class="missed-item__cell">
                实际：<b class="missed-item__actual">{{ row.actual }}</b>
              </td>
            </tr>
          </table>
        </div>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  report: { type: Object, default: null },
})

const DIM_LABELS = {
  font: '字体',
  font_size: '字号',
  bold: '加粗',
  line_spacing: '行距',
  paragraph_space: '段间距',
}
const DIM_KEYS = {
  font: ['font_name'],
  font_size: ['font_size_pt'],
  bold: ['bold'],
  line_spacing: ['line_spacing_rule', 'line_spacing_value'],
  paragraph_space: ['space_before_pt', 'space_after_pt'],
}

function fmt(v) {
  if (typeof v === 'boolean') return v ? '是' : '否'
  if (v === null || v === undefined || v === '') return '—'
  return String(v)
}

const missedList = computed(() => props.report?.missed || [])

function dimRows(item) {
  const rows = []
  const dims = String(item.reason || '').split(',').filter(Boolean)
  for (const dim of dims) {
    for (const key of DIM_KEYS[dim] || []) {
      rows.push({
        label: `${DIM_LABELS[dim] || dim} · ${key}`,
        expected: fmt(item.expected && item.expected[key]),
        actual: fmt(item.actual && item.actual[key]),
      })
    }
  }
  return rows
}
</script>

<style scoped>
.report {
  max-width: 480px;
  margin: 0 auto 32px;
  padding: 20px;
  background: rgba(255, 255, 255, 0.3);
  backdrop-filter: blur(12px) saturate(165%);
  -webkit-backdrop-filter: blur(12px) saturate(165%);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-md);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.5);
  text-align: left;
}

.report__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.report__title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.report__coverage {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-tertiary);
}

.report__coverage.is-pass {
  color: var(--success-500, #10b981);
}

.report__coverage.is-fail {
  color: var(--error-500);
}

.report__meta {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0 0 12px;
}

.missed-item {
  padding: 12px 0;
  border-top: 1px solid var(--border-color);
}

.missed-item__head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 8px;
}

.missed-item__tag {
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(245, 158, 11, 0.15);
  color: #b45309;
}

.missed-item__text {
  font-size: 13px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.missed-item__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  color: var(--text-secondary);
}

.missed-item__table td {
  padding: 3px 0;
}

.missed-item__dim {
  width: 110px;
  font-weight: 600;
  color: var(--text-primary);
}

.missed-item__actual {
  color: var(--error-500);
}
</style>

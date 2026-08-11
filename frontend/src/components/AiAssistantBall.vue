<template>
  <div class="ai-ball">
    <!-- 悬浮球 -->
    <button
      ref="ballRef"
      class="ai-ball__fab"
      :class="{ 'ai-ball__fab--open': open }"
      :style="ballStyle"
      aria-label="AI 助手"
      @pointerdown="onPointerDown"
    >
      <el-icon :size="26"><ChatDotRound /></el-icon>
      <span class="ai-ball__pulse"></span>
    </button>

    <!-- 聊天面板 -->
    <transition name="ai-ball-pop">
      <div
        v-if="open"
        class="ai-ball__panel"
        :style="panelStyle"
        @pointerdown.stop
      >
        <div class="ai-ball__header">
          <div class="ai-ball__header-icon">
            <el-icon :size="18"><ChatDotRound /></el-icon>
          </div>
          <div class="ai-ball__header-text">
            <span class="ai-ball__header-title">AI 助手</span>
            <span class="ai-ball__header-desc">模板推荐 · 排版咨询</span>
          </div>
          <button class="ai-ball__close" @click="open = false">
            <el-icon><Close /></el-icon>
          </button>
        </div>

        <div ref="scrollRef" class="ai-ball__body">
          <div v-if="messages.length === 0" class="ai-ball__empty">
            <div class="ai-ball__empty-icon">
              <el-icon :size="30"><MagicStick /></el-icon>
            </div>
            <p>告诉我你的行业和文档类型，我帮你推荐最合适的排版模板</p>
            <button
              v-for="q in suggestions"
              :key="q"
              class="ai-ball__suggestion"
              @click="send(q)"
            >
              {{ q }}
            </button>
          </div>

          <div
            v-for="(msg, idx) in messages"
            :key="idx"
            class="ai-ball__row"
            :class="`ai-ball__row--${msg.role}`"
          >
            <div class="ai-ball__avatar" :class="`ai-ball__avatar--${msg.role}`">
              <el-icon v-if="msg.role === 'assistant'" :size="15"><ChatDotRound /></el-icon>
              <el-icon v-else :size="15"><UserFilled /></el-icon>
            </div>
            <div class="ai-ball__bubble" v-html="renderText(msg.content)"></div>
          </div>

          <div v-if="loading" class="ai-ball__row ai-ball__row--assistant">
            <div class="ai-ball__avatar ai-ball__avatar--assistant">
              <el-icon :size="15"><ChatDotRound /></el-icon>
            </div>
            <div class="ai-ball__bubble ai-ball__bubble--typing">
              <span class="ai-ball__dot"></span>
              <span class="ai-ball__dot"></span>
              <span class="ai-ball__dot"></span>
            </div>
          </div>
        </div>

        <div class="ai-ball__input">
          <el-input
            v-model="draft"
            type="textarea"
            :rows="2"
            resize="none"
            placeholder="输入行业和文档类型，Enter 发送"
            maxlength="2000"
            @keydown.enter.exact.prevent="send()"
          />
          <el-button
            type="primary"
            class="ai-ball__send"
            :disabled="!draft.trim() || loading"
            :loading="loading"
            @click="send()"
          >
            发送
          </el-button>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { ChatDotRound, Close, MagicStick, UserFilled } from '@element-plus/icons-vue'
import { getChatHistory, sendChat } from '@/api/chat.js'
import { useAuthStore } from '@/stores/auth.js'

const { isLoggedIn } = useAuthStore()

const open = ref(false)
const draft = ref('')
const loading = ref(false)
const messages = ref([])
const scrollRef = ref(null)
const ballRef = ref(null)

const FAB_SIZE = 58
const pos = ref({ x: 0, y: 0 })
const dragState = ref(null)

const suggestions = [
  '教育行业的本科毕业论文该用哪个模板？',
  '政府单位的红头文件怎么排版？',
  '创业公司写商业计划书用什么模板？',
]

function clampPos(x, y) {
  const maxX = Math.max(0, window.innerWidth - FAB_SIZE - 12)
  const maxY = Math.max(0, window.innerHeight - FAB_SIZE - 12)
  return {
    x: Math.min(Math.max(12, x), maxX),
    y: Math.min(Math.max(12, y), maxY),
  }
}

function initPos() {
  pos.value = clampPos(window.innerWidth - FAB_SIZE - 28, window.innerHeight - FAB_SIZE - 140)
}

const ballStyle = computed(() => ({
  transform: `translate(${pos.value.x}px, ${pos.value.y}px)`,
}))

const panelStyle = computed(() => {
  const rightSide = pos.value.x > window.innerWidth / 2
  const panelW = Math.min(380, window.innerWidth - 24)
  const panelH = Math.min(540, window.innerHeight - 96)
  let left = rightSide ? pos.value.x - panelW - 14 : pos.value.x + FAB_SIZE + 14
  left = Math.min(Math.max(12, left), window.innerWidth - panelW - 12)
  let top = pos.value.y + FAB_SIZE / 2 - panelH / 2
  top = Math.min(Math.max(64, top), window.innerHeight - panelH - 12)
  return {
    left: `${left}px`,
    top: `${top}px`,
    width: `${panelW}px`,
    height: `${panelH}px`,
    transformOrigin: rightSide ? 'right center' : 'left center',
  }
})

function onPointerDown(e) {
  if (e.button !== 0) return
  const startX = e.clientX
  const startY = e.clientY
  dragState.value = {
    startX,
    startY,
    originX: pos.value.x,
    originY: pos.value.y,
    moved: false,
  }
  ballRef.value?.setPointerCapture(e.pointerId)
}

function onPointerMove(e) {
  const s = dragState.value
  if (!s) return
  const dx = e.clientX - s.startX
  const dy = e.clientY - s.startY
  if (Math.abs(dx) + Math.abs(dy) > 5) s.moved = true
  pos.value = clampPos(s.originX + dx, s.originY + dy)
}

function onPointerUp(e) {
  const s = dragState.value
  if (!s) return
  dragState.value = null
  ballRef.value?.releasePointerCapture(e.pointerId)
  if (!s.moved) {
    open.value = !open.value
    if (open.value) loadHistory()
  }
}

function handleOpenEvent() {
  open.value = true
  loadHistory()
}

function renderText(text) {
  return (text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br/>')
}

async function scrollToBottom() {
  await nextTick()
  if (scrollRef.value) {
    scrollRef.value.scrollTop = scrollRef.value.scrollHeight
  }
}

async function loadHistory() {
  if (!isLoggedIn.value || messages.value.length) return
  try {
    const data = await getChatHistory()
    messages.value = (data.messages || []).slice().reverse()
    await scrollToBottom()
  } catch {
    // 历史加载失败不影响继续聊天
  }
}

async function send(text) {
  const message = (text ?? draft.value).trim()
  if (!message || loading.value) return
  messages.value.push({ role: 'user', content: message })
  draft.value = ''
  loading.value = true
  await scrollToBottom()
  try {
    const data = await sendChat(message)
    messages.value.push({ role: 'assistant', content: data.answer, sources: data.sources || [] })
  } catch (err) {
    const raw = err.message || ''
    const friendly = raw.includes('Status code') || raw.includes('Internal Server Error')
      ? 'AI 服务暂时不可用，请稍后再试'
      : raw
    messages.value.push({ role: 'assistant', content: friendly })
    ElMessage.error(friendly)
  } finally {
    loading.value = false
    await scrollToBottom()
  }
}

onMounted(() => {
  initPos()
  window.addEventListener('resize', initPos)
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerUp)
  window.addEventListener('docagent:open-ai', handleOpenEvent)
})

onUnmounted(() => {
  window.removeEventListener('resize', initPos)
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
  window.removeEventListener('docagent:open-ai', handleOpenEvent)
})
</script>

<style scoped>
.ai-ball__fab {
  position: fixed;
  left: 0;
  top: 0;
  width: 58px;
  height: 58px;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.55);
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: grab;
  z-index: 1000;
  box-shadow: 0 10px 28px rgba(79, 70, 229, 0.38), inset 0 1px 0 rgba(255, 255, 255, 0.35);
  transition: transform var(--transition-base), box-shadow var(--transition-base);
  touch-action: none;
  user-select: none;
  -webkit-user-select: none;
}

.ai-ball__fab:active {
  cursor: grabbing;
}

.ai-ball__fab--open {
  box-shadow: 0 14px 34px rgba(79, 70, 229, 0.48), inset 0 1px 0 rgba(255, 255, 255, 0.35);
}

.ai-ball__pulse {
  position: absolute;
  inset: -5px;
  border-radius: 50%;
  border: 2px solid rgba(99, 102, 241, 0.45);
  animation: ai-ball-pulse 2.4s ease-out infinite;
  pointer-events: none;
}

@keyframes ai-ball-pulse {
  0% {
    transform: scale(0.9);
    opacity: 0.9;
  }
  100% {
    transform: scale(1.45);
    opacity: 0;
  }
}

.ai-ball__panel {
  position: fixed;
  z-index: 1001;
  display: flex;
  flex-direction: column;
  background: rgba(255, 255, 255, 0.86);
  backdrop-filter: blur(24px) saturate(170%);
  -webkit-backdrop-filter: blur(24px) saturate(170%);
  border: 1px solid var(--glass-border);
  border-radius: 20px;
  box-shadow: var(--glass-shadow-lg), var(--glass-highlight);
  overflow: hidden;
}

.ai-ball__header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.14), rgba(255, 255, 255, 0.30));
  border-bottom: 1px solid rgba(255, 255, 255, 0.40);
}

.ai-ball__header-icon {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
}

.ai-ball__header-text {
  flex: 1;
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}

.ai-ball__header-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}

.ai-ball__header-desc {
  font-size: 12px;
  color: var(--text-tertiary);
}

.ai-ball__close {
  width: 30px;
  height: 30px;
  border: none;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.40);
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.ai-ball__close:hover {
  background: rgba(99, 102, 241, 0.14);
  color: var(--brand-600);
}

.ai-ball__body {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.ai-ball__empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: 10px;
}

.ai-ball__empty-icon {
  width: 56px;
  height: 56px;
  border-radius: 16px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.16), rgba(255, 255, 255, 0.36));
  border: 1px solid rgba(255, 255, 255, 0.48);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--brand-600);
}

.ai-ball__empty p {
  font-size: 13px;
  color: var(--text-secondary);
  max-width: 260px;
  margin: 0;
}

.ai-ball__suggestion {
  padding: 7px 12px;
  background: rgba(255, 255, 255, 0.40);
  border: 1px solid var(--glass-border);
  border-radius: 9999px;
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.ai-ball__suggestion:hover {
  background: rgba(99, 102, 241, 0.14);
  color: var(--brand-600);
  border-color: var(--brand-500);
}

.ai-ball__row {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
}

.ai-ball__row--user {
  flex-direction: row-reverse;
}

.ai-ball__avatar {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.ai-ball__avatar--assistant {
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  color: white;
}

.ai-ball__avatar--user {
  background: rgba(148, 163, 184, 0.35);
  color: var(--text-secondary);
}

.ai-ball__bubble {
  max-width: 82%;
  padding: 10px 13px;
  border-radius: 14px;
  font-size: 13px;
  line-height: 1.7;
  word-break: break-word;
}

.ai-ball__row--assistant .ai-ball__bubble {
  background: rgba(255, 255, 255, 0.55);
  border: 1px solid rgba(255, 255, 255, 0.55);
  border-top-left-radius: 4px;
  color: var(--text-primary);
}

.ai-ball__row--user .ai-ball__bubble {
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  color: white;
  border-top-right-radius: 4px;
}

.ai-ball__bubble :deep(strong) {
  font-weight: 700;
}

.ai-ball__bubble :deep(code) {
  padding: 1px 5px;
  background: rgba(99, 102, 241, 0.12);
  border-radius: 4px;
  font-size: 12px;
}

.ai-ball__bubble--typing {
  display: flex;
  gap: 4px;
  align-items: center;
  min-height: 26px;
}

.ai-ball__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--brand-400);
  animation: ai-ball-typing 1.2s infinite ease-in-out;
}

.ai-ball__dot:nth-child(2) {
  animation-delay: 0.15s;
}

.ai-ball__dot:nth-child(3) {
  animation-delay: 0.3s;
}

@keyframes ai-ball-typing {
  0%, 60%, 100% {
    transform: translateY(0);
    opacity: 0.4;
  }
  30% {
    transform: translateY(-4px);
    opacity: 1;
  }
}

.ai-ball__input {
  display: flex;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.40);
  background: rgba(255, 255, 255, 0.35);
}

.ai-ball__input :deep(.el-textarea__inner) {
  border-radius: 10px;
  font-size: 13px;
  background: rgba(255, 255, 255, 0.55);
}

.ai-ball__send {
  align-self: flex-end;
  height: 38px;
  padding: 0 16px;
  border-radius: 10px;
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  border: none;
  font-size: 13px;
  font-weight: 600;
}

.ai-ball-pop-enter-active,
.ai-ball-pop-leave-active {
  transition: opacity var(--transition-slow), transform var(--transition-slow);
}

.ai-ball-pop-enter-from,
.ai-ball-pop-leave-to {
  opacity: 0;
  transform: scale(0.92) translateY(8px);
}

@media (max-width: 720px) {
  .ai-ball__panel {
    width: calc(100vw - 24px) !important;
    left: 12px !important;
    right: 12px !important;
  }
}
</style>

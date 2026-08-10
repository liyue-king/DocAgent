<template>
  <div class="chat-page">
    <AppNavbar />

    <main class="chat-page__main">
      <div class="chat-page__container">
        <div class="chat-page__header">
          <div class="chat-page__header-icon">
            <el-icon :size="22"><ChatDotRound /></el-icon>
          </div>
          <div>
            <h1 class="chat-page__title">模板推荐助手</h1>
            <p class="chat-page__desc">告诉我你的行业和文档类型，我帮你选最合适的排版模板</p>
          </div>
        </div>

        <div ref="scrollRef" class="chat-card">
          <div v-if="messages.length === 0" class="chat-card__empty">
            <div class="chat-card__empty-icon">
              <el-icon :size="40"><MagicStick /></el-icon>
            </div>
            <h3>问问 AI 助手</h3>
            <p>例如：教育行业的本科毕业论文该用哪个模板？政府单位的公文怎么排版？</p>
            <div class="chat-card__suggestions">
              <button
                v-for="q in suggestions"
                :key="q"
                class="chat-card__suggestion"
                @click="send(q)"
              >
                {{ q }}
              </button>
            </div>
          </div>

          <div v-for="(msg, idx) in messages" :key="idx" class="chat-row" :class="`chat-row--${msg.role}`">
            <div class="chat-row__avatar" :class="`chat-row__avatar--${msg.role}`">
              <el-icon v-if="msg.role === 'assistant'"><ChatDotRound /></el-icon>
              <el-icon v-else><UserFilled /></el-icon>
            </div>
            <div class="chat-row__body">
              <div class="chat-row__bubble">
                <span class="chat-row__text" v-html="renderText(msg.content)"></span>
              </div>
              <div v-if="msg.sources?.length" class="chat-row__sources">
                <span class="chat-row__sources-label">参考来源</span>
                <button
                  v-for="(src, si) in msg.sources.slice(0, 5)"
                  :key="si"
                  class="chat-row__source"
                  :title="src.content"
                >
                  {{ src.category || '未分类' }} · {{ src.title }}
                </button>
              </div>
            </div>
          </div>

          <div v-if="loading" class="chat-row chat-row--assistant">
            <div class="chat-row__avatar chat-row__avatar--assistant">
              <el-icon><ChatDotRound /></el-icon>
            </div>
            <div class="chat-row__body">
              <div class="chat-row__bubble chat-row__bubble--typing">
                <span class="dot"></span><span class="dot"></span><span class="dot"></span>
              </div>
            </div>
          </div>
        </div>

        <div class="chat-page__input">
          <el-input
            v-model="draft"
            type="textarea"
            :rows="2"
            resize="none"
            placeholder="输入你的行业和文档类型，例如：律师事务所的合同模板"
            maxlength="2000"
            @keydown.enter.exact.prevent="send()"
          />
          <el-button
            type="primary"
            class="chat-page__send"
            :disabled="!draft.trim() || loading"
            :loading="loading"
            @click="send()"
          >
            发送
          </el-button>
        </div>
      </div>
    </main>

    <AppFooter />
  </div>
</template>

<script setup>
import { ref, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { ChatDotRound, MagicStick, UserFilled } from '@element-plus/icons-vue'
import AppNavbar from '@/components/AppNavbar.vue'
import AppFooter from '@/components/AppFooter.vue'
import { sendChat } from '@/api/chat.js'

const draft = ref('')
const loading = ref(false)
const scrollRef = ref(null)
const messages = ref([])

const suggestions = [
  '教育行业的本科毕业论文该用哪个模板？',
  '政府单位的红头文件怎么排版？',
  '创业公司写商业计划书用什么模板？',
]

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
    messages.value.push({ role: 'assistant', content: err.message || '请求失败，请稍后再试' })
    ElMessage.error(err.message || '请求失败')
  } finally {
    loading.value = false
    await scrollToBottom()
  }
}
</script>

<style scoped>
.chat-page__main {
  min-height: calc(100vh - 200px);
  padding: 120px 24px 40px;
  background: transparent;
}

.chat-page__container {
  max-width: 860px;
  margin: 0 auto;
}

.chat-page__header {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 24px;
}

.chat-page__header-icon {
  width: 48px;
  height: 48px;
  border-radius: 14px;
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 8px 20px rgba(79, 70, 229, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.32);
}

.chat-page__title {
  font-size: 26px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}

.chat-page__desc {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 4px 0 0;
}

.chat-card {
  height: calc(100vh - 380px);
  min-height: 360px;
  overflow-y: auto;
  padding: 24px;
  background: var(--glass-surface-strong);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--glass-shadow-lg), var(--glass-highlight);
  scroll-behavior: smooth;
}

.chat-card__empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  color: var(--text-secondary);
}

.chat-card__empty-icon {
  width: 76px;
  height: 76px;
  border-radius: 22px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.18), rgba(255, 255, 255, 0.32));
  border: 1px solid rgba(255, 255, 255, 0.48);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--brand-600);
  margin-bottom: 18px;
}

.chat-card__empty h3 {
  font-size: 18px;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.chat-card__empty p {
  font-size: 14px;
  max-width: 420px;
  margin: 0 0 20px;
}

.chat-card__suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
}

.chat-card__suggestion {
  padding: 8px 14px;
  background: rgba(255, 255, 255, 0.30);
  border: 1px solid var(--glass-border);
  border-radius: 9999px;
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.chat-card__suggestion:hover {
  background: rgba(99, 102, 241, 0.14);
  color: var(--brand-600);
  border-color: var(--brand-500);
}

.chat-row {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}

.chat-row--user {
  flex-direction: row-reverse;
}

.chat-row__avatar {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
}

.chat-row__avatar--assistant {
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  color: white;
}

.chat-row__avatar--user {
  background: rgba(148, 163, 184, 0.35);
  color: var(--text-secondary);
}

.chat-row__body {
  max-width: 78%;
}

.chat-row--user .chat-row__body {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.chat-row__bubble {
  padding: 12px 16px;
  border-radius: 16px;
  font-size: 14px;
  line-height: 1.7;
  word-break: break-word;
}

.chat-row--assistant .chat-row__bubble {
  background: rgba(255, 255, 255, 0.36);
  backdrop-filter: blur(12px) saturate(165%);
  -webkit-backdrop-filter: blur(12px) saturate(165%);
  border: 1px solid var(--glass-border);
  border-top-left-radius: 4px;
  color: var(--text-primary);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.50);
}

.chat-row--user .chat-row__bubble {
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  color: white;
  border-top-right-radius: 4px;
  box-shadow: 0 6px 18px rgba(79, 70, 229, 0.24);
}

.chat-row__text :deep(strong) {
  font-weight: 700;
}

.chat-row__text :deep(code) {
  padding: 1px 6px;
  background: rgba(99, 102, 241, 0.12);
  border-radius: 5px;
  font-size: 13px;
}

.chat-row__sources {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.chat-row--user .chat-row__sources {
  display: none;
}

.chat-row__sources-label {
  font-size: 12px;
  color: var(--text-tertiary);
  line-height: 26px;
}

.chat-row__source {
  padding: 3px 10px;
  background: rgba(99, 102, 241, 0.10);
  border: 1px solid rgba(99, 102, 241, 0.24);
  border-radius: 9999px;
  font-size: 12px;
  color: var(--brand-600);
  cursor: default;
}

.chat-row__bubble--typing {
  display: flex;
  gap: 5px;
  align-items: center;
  min-height: 30px;
}

.chat-row__bubble--typing .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--brand-400);
  animation: typing-bounce 1.2s infinite ease-in-out;
}

.chat-row__bubble--typing .dot:nth-child(2) {
  animation-delay: 0.15s;
}

.chat-row__bubble--typing .dot:nth-child(3) {
  animation-delay: 0.3s;
}

@keyframes typing-bounce {
  0%, 60%, 100% {
    transform: translateY(0);
    opacity: 0.4;
  }
  30% {
    transform: translateY(-5px);
    opacity: 1;
  }
}

.chat-page__input {
  display: flex;
  gap: 12px;
  margin-top: 16px;
  padding: 14px;
  background: var(--glass-surface-strong);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--glass-shadow), var(--glass-highlight);
}

.chat-page__input :deep(.el-textarea__inner) {
  border-radius: var(--radius-md);
  font-size: 14px;
  background: rgba(255, 255, 255, 0.26);
}

.chat-page__send {
  align-self: flex-end;
  height: 42px;
  padding: 0 28px;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  border: none;
  font-weight: 600;
}

@media (max-width: 720px) {
  .chat-card {
    height: calc(100vh - 430px);
    padding: 16px;
  }

  .chat-row__body {
    max-width: 84%;
  }
}
</style>

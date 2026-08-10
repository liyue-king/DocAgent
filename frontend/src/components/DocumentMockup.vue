<template>
  <div class="document-mockup" :class="`document-mockup--${variant}`">
    <div class="document-mockup__window">
      <div class="document-mockup__header">
        <span class="document-mockup__dot"></span>
        <span class="document-mockup__dot"></span>
        <span class="document-mockup__dot"></span>
      </div>
      <div class="document-mockup__content">
        <div class="document-mockup__title"></div>
        <div class="document-mockup__line document-mockup__line--short"></div>
        <div class="document-mockup__line"></div>
        <div class="document-mockup__line"></div>
        <div class="document-mockup__line"></div>
        <div class="document-mockup__line document-mockup__line--short"></div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  variant: {
    type: String,
    default: 'default',
  },
})
</script>

<style scoped>
.document-mockup {
  position: relative;
}

.document-mockup__window {
  width: 280px;
  background: var(--glass-surface);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--glass-shadow-lg), var(--glass-highlight);
  overflow: hidden;
  transform: rotate(-3deg);
  transition: transform var(--transition-base);
}

.document-mockup:hover .document-mockup__window {
  transform: rotate(0deg) translateY(-4px);
}

.document-mockup__header {
  display: flex;
  gap: 6px;
  padding: 12px 16px;
  background: rgba(255, 255, 255, 0.24);
  border-bottom: 1px solid rgba(255, 255, 255, 0.32);
}

.document-mockup__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #E2E8F0;
}

.document-mockup__content {
  padding: 20px;
}

.document-mockup__title {
  width: 60%;
  height: 16px;
  background: linear-gradient(90deg, rgba(148, 163, 184, 0.35), rgba(203, 213, 225, 0.25));
  border-radius: 4px;
  margin-bottom: 16px;
}

.document-mockup__line {
  height: 10px;
  background: rgba(148, 163, 184, 0.2);
  border-radius: 3px;
  margin-bottom: 10px;
}

.document-mockup__line--short {
  width: 75%;
}
</style>

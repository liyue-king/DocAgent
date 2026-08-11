<template>
  <div class="app-scene" aria-hidden="true">
    <span class="app-scene__orb app-scene__orb--indigo"></span>
    <span class="app-scene__orb app-scene__orb--cyan"></span>
    <span class="app-scene__orb app-scene__orb--emerald"></span>
    <span class="app-scene__orb app-scene__orb--pink"></span>
    <span class="app-scene__orb app-scene__orb--amber"></span>
    <div class="app-scene__grain"></div>
  </div>
  <div class="app-shell">
    <router-view />
    <AiAssistantBall />
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth.js'
import AiAssistantBall from '@/components/AiAssistantBall.vue'

const { fetchCurrentUser } = useAuthStore()

// 应用启动时刷新用户信息（如支付后余额变化、token 过期检测）
onMounted(() => {
  fetchCurrentUser()
})
</script>

<style>
.app-scene {
  position: fixed;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  pointer-events: none;
}

.app-shell {
  position: relative;
  z-index: 1;
}

.app-scene__orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(78px);
  will-change: transform;
}

.app-scene__orb--indigo {
  width: 540px;
  height: 540px;
  left: -160px;
  top: -140px;
  background: radial-gradient(circle at 32% 30%, var(--orb-indigo) 0%, transparent 68%);
  animation: orb-drift-1 26s ease-in-out infinite alternate;
}

.app-scene__orb--cyan {
  width: 460px;
  height: 460px;
  right: -140px;
  top: 8%;
  background: radial-gradient(circle at 60% 40%, var(--orb-cyan) 0%, transparent 68%);
  animation: orb-drift-2 31s ease-in-out infinite alternate;
}

.app-scene__orb--emerald {
  width: 480px;
  height: 480px;
  left: 6%;
  bottom: -180px;
  background: radial-gradient(circle at 40% 60%, var(--orb-emerald) 0%, transparent 68%);
  animation: orb-drift-3 36s ease-in-out infinite alternate;
}

.app-scene__orb--pink {
  width: 440px;
  height: 440px;
  right: 4%;
  bottom: -160px;
  background: radial-gradient(circle at 55% 55%, var(--orb-pink) 0%, transparent 68%);
  animation: orb-drift-1 29s ease-in-out infinite alternate-reverse;
}

.app-scene__orb--amber {
  width: 300px;
  height: 300px;
  left: 46%;
  top: 58%;
  background: radial-gradient(circle at 50% 50%, var(--orb-amber) 0%, transparent 66%);
  animation: orb-drift-2 24s ease-in-out infinite alternate-reverse;
}

.app-scene__grain {
  position: absolute;
  inset: 0;
  opacity: 0.055;
  mix-blend-mode: overlay;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix type='saturate' values='0'/></filter><rect width='100%25' height='100%25' filter='url(%23n)' opacity='0.7'/></svg>");
}

@keyframes orb-drift-1 {
  from {
    transform: translate(0, 0) scale(1);
  }
  to {
    transform: translate(76px, 48px) scale(1.12);
  }
}

@keyframes orb-drift-2 {
  from {
    transform: translate(0, 0) scale(1.05);
  }
  to {
    transform: translate(-60px, 64px) scale(0.94);
  }
}

@keyframes orb-drift-3 {
  from {
    transform: translate(0, 0) scale(0.96);
  }
  to {
    transform: translate(52px, -58px) scale(1.08);
  }
}
</style>

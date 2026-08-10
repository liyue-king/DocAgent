<template>
  <div class="animated-check">
    <svg class="animated-check__svg" viewBox="0 0 52 52">
      <circle class="animated-check__circle" cx="26" cy="26" r="25" fill="none"/>
      <path class="animated-check__check" fill="none" d="M14.1 27.2l7.1 7.2 16.7-16.8"/>
    </svg>
  </div>
</template>

<style scoped>
.animated-check {
  width: 80px;
  height: 80px;
}

.animated-check__svg {
  width: 100%;
  height: 100%;
}

.animated-check__circle {
  stroke: var(--success-500);
  stroke-width: 2;
  stroke-dasharray: 166;
  stroke-dashoffset: 166;
  stroke-linecap: round;
  animation: stroke 0.6s cubic-bezier(0.65, 0, 0.45, 1) forwards;
}

.animated-check__check {
  stroke: var(--success-500);
  stroke-width: 3;
  stroke-dasharray: 48;
  stroke-dashoffset: 48;
  stroke-linecap: round;
  stroke-linejoin: round;
  animation: stroke 0.3s cubic-bezier(0.65, 0, 0.45, 1) 0.5s forwards;
}

@keyframes stroke {
  100% {
    stroke-dashoffset: 0;
  }
}
</style>

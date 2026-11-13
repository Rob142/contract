import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// 브라우저는 같은 출처(/api)로 요청하고, 개발 서버가 API로 넘긴다. 그래서 CORS가 필요 없다.
const apiTarget = process.env.API_PROXY_TARGET ?? 'http://127.0.0.1:8010'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    // 윈도우 + Docker에서는 파일 변경 알림이 오지 않아 폴링으로 감지한다 (.env의 FILE_POLLING=true)
    watch: process.env.FILE_POLLING === 'true' ? { usePolling: true, interval: 500 } : undefined,
    proxy: {
      // Origin 헤더를 그대로 넘겨 백엔드의 CSRF Origin 검사가 동작하게 한다
      '/api': { target: apiTarget, changeOrigin: false },
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})

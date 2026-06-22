import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
//
// In dev the frontend talks to the backend through Vite's proxy: requests to
// /api/* are forwarded to the FastAPI server. This keeps the browser on a single
// origin (no CORS), and — combined with the retrying axios client — lets the UI
// survive a backend restart without a hard page reload. Override the target with
// VITE_PROXY_TARGET if the backend runs somewhere other than :8000.
const PROXY_TARGET = process.env.VITE_PROXY_TARGET ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: PROXY_TARGET,
        changeOrigin: true,
        // SSE (/api/question/stream) must stream, not buffer.
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            if (proxyRes.headers['content-type']?.includes('text/event-stream')) {
              proxyRes.headers['cache-control'] = 'no-cache'
            }
          })
        },
      },
    },
  },
})

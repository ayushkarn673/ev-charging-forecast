import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The dev server proxies /api to the Spring Boot backend, so the browser only talks to one origin.
const backend = process.env.BACKEND_URL ?? 'http://127.0.0.1:8080'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: { '/api': { target: backend, changeOrigin: false } },
  },
  preview: {
    host: '127.0.0.1',
    port: 4173,
    proxy: { '/api': { target: backend, changeOrigin: false } },
  },
})

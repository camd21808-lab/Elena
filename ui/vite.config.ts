import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  base: './',
  server: {
    host: true,
    port: 5173,
    strictPort: true,
    proxy: {
      '/jobs': 'http://localhost:8000',
      '/convert': 'http://localhost:8000',
      '/protect': 'http://localhost:8000',
      '/library': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
      '/auth': 'http://localhost:8000',
      '/settings': 'http://localhost:8000',
    },
  },
})

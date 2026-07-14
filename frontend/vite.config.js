import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/chat': 'http://127.0.0.1:8000',
      '/voice': 'http://127.0.0.1:8000',
      '/products': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
      '/stats': 'http://127.0.0.1:8000',
      '/stores': 'http://127.0.0.1:8000',
    },
  },
})

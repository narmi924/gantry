import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
        // a viewer closing the tab mid-message must not take the dev server down
        configure: (proxy) => {
          proxy.on('error', () => {})
        },
      },
    },
  },
})

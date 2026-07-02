import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Base is set to './' so the built app works when served from any sub-path
// (e.g. GitHub Pages project sites) without extra configuration.
export default defineConfig({
  plugins: [react()],
  base: './',
  server: {
    host: true,
    port: 5173,
  },
})

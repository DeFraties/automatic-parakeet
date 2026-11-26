/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Allow GitHub Codespaces' forwarded-port addresses (e.g. name-5173.app.github.dev).
    allowedHosts: ['.app.github.dev'],
    proxy: { '/api': { target: process.env.API_URL ?? 'http://127.0.0.1:8000', changeOrigin: false } },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/**/*.test.{ts,tsx}'],
    css: false,
    globals: true,
  },
});

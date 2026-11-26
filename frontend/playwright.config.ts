import { defineConfig, devices } from '@playwright/test';

// Starts a throwaway API (fresh SQLite DB, migrated + seeded) and the Vite dev server.
const API_PORT = 8765;
const WEB_PORT = 5174;
const DB = 'sqlite:///./data/e2e.db';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  reporter: 'list',
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: 'off',
    permissions: ['clipboard-read', 'clipboard-write'],
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['Pixel 7'] } },
  ],
  webServer: [
    {
      command:
        `cd .. && rm -f data/e2e.db* && export DATABASE_URL=${DB} RATE_LIMIT_GAMES_PER_HOUR=0 ` +
        `RATE_LIMIT_GUESSES_PER_HOUR=0 && backend/.venv/bin/alembic -c backend/alembic.ini upgrade head ` +
        `&& backend/.venv/bin/python -m app.seed ` +
        `&& backend/.venv/bin/uvicorn app.main:app --port ${API_PORT}`,
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npx vite --port ${WEB_PORT} --strictPort --host 127.0.0.1`,
      url: `http://127.0.0.1:${WEB_PORT}`,
      env: { API_URL: `http://127.0.0.1:${API_PORT}` },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});

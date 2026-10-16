import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.CONSOLE_BASE_URL || 'http://localhost',
    headless: true,
    ignoreHTTPSErrors: true,
    actionTimeout: 15_000,
  },
});

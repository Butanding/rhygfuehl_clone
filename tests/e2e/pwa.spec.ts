import { test, expect } from '@playwright/test';

test.describe('PWA Service Worker', () => {
  test('should register service worker', async ({ page }) => {
    await page.goto('/');

    // Verify service worker is registered
    const isSWRegistered = await page.evaluate(async () => {
      if (!('serviceWorker' in navigator)) return false;
      const registration = await navigator.serviceWorker.ready;
      return !!registration;
    });

    expect(isSWRegistered).toBe(true);
  });

});


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

  test('should have update toast UI elements', async ({ page }) => {
    await page.goto('/');

    // Toast should initially be hidden (translated down by 200%)
    const toast = page.locator('#pwa-toast');
    await expect(toast).toHaveClass(/translate-y-\[200%\]/);

    const refreshBtn = page.locator('#pwa-refresh');
    const closeBtn = page.locator('#pwa-close');

    // Remove the hidden class to simulate an update (needRefresh event)
    await page.evaluate(() => {
      document.getElementById('pwa-toast')?.classList.remove('translate-y-[200%]');
    });

    // Now it should be visible (translated up)
    await expect(toast).not.toHaveClass(/translate-y-\[200%\]/);

    // Click close and verify it hides again
    await closeBtn.click();
    await expect(toast).toHaveClass(/translate-y-\[200%\]/);
  });
});

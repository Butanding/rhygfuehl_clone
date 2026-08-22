import { test, expect } from '@playwright/test';

test.describe('Home Page', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('has correct title and basic metrics (German)', async ({ page }) => {
    await expect(page).toHaveTitle(/Rhygfuehl/i);

    const waterTempHeader = page.getByRole('heading', { name: /Wassertemperatur/i });
    await expect(waterTempHeader.first()).toBeVisible();

    const airTempHeader = page.getByRole('heading', { name: /Lufttemperatur/i });
    await expect(airTempHeader.first()).toBeVisible();

    // const prognosisHeader = page.getByRole('heading', { name: /Bade-Empfehlung/i });
    // await expect(prognosisHeader.first()).toBeVisible();
  });

  test('can expand and collapse metric details', async ({ page }) => {
    const firstToggle = page.locator('.metric-toggle').first();
    const collapseGrid = page.locator('.collapse-grid').first();

    // Ensure it's closed initially
    await expect(collapseGrid).not.toHaveClass(/is-open/);

    // Click to open
    await firstToggle.click();
    await expect(collapseGrid).toHaveClass(/is-open/);

    // Click again to close
    await firstToggle.click();
    await expect(collapseGrid).not.toHaveClass(/is-open/);
  });

  test('can switch to English translation', async ({ page }) => {
    // Look for link with exact href or text
    const enLink = page.locator('footer a[href="/en/"], nav a[href="/en/"], a[href="/en/"]').first();
    
    if (await enLink.isVisible()) {
      await enLink.click();
      await expect(page).toHaveURL(/\/en\//);

      const waterTempHeaderEn = page.getByRole('heading', { name: /Water temperature/i });
      await expect(waterTempHeaderEn.first()).toBeVisible();

      // const prognosisHeaderEn = page.getByRole('heading', { name: /Swimming Recommendation/i });
      // await expect(prognosisHeaderEn.first()).toBeVisible();
    }
  });

  test('can navigate to Impressum', async ({ page }) => {
    const impressumLink = page.getByRole('link', { name: /Impressum/i }).first();
    await impressumLink.click();

    await expect(page).toHaveURL(/\/impressum/);
    const impressumHeading = page.getByRole('heading', { name: /Impressum/i }).first();
    await expect(impressumHeading).toBeVisible();

    const backLink = page.getByRole('link', { name: /Zurück/i }).first();
    await backLink.click();
    await expect(page).toHaveURL(/\//);
  });

  test('exposes WebMCP manifest with tools, prompts, and resources', async ({ page }) => {
    // Wait for the client scripts to execute
    await page.waitForFunction(() => (window as any).__webmcp !== undefined);

    const mcpState = await page.evaluate(async () => {
      const manifest = (window as any).__webmcp;
      const tempTool = manifest.tools.find((t: any) => t.name === 'get_rhine_temperature');
      const tempResult = tempTool ? await tempTool.execute() : null;

      return {
        hasTools: manifest.tools.length === 3,
        toolNames: manifest.tools.map((t: any) => t.name),
        hasPrompts: manifest.prompts.length === 3,
        promptNames: manifest.prompts.map((p: any) => p.name),
        hasResources: manifest.resources.length === 4,
        resourceUris: manifest.resources.map((r: any) => r.uri),
        tempResultParsed: tempResult ? JSON.parse(tempResult.content[0].text) : null
      };
    });

    expect(mcpState.hasTools).toBe(true);
    expect(mcpState.toolNames).toContain('get_rhine_temperature');
    expect(mcpState.toolNames).toContain('get_swimming_prognosis');
    expect(mcpState.toolNames).toContain('get_rhine_history');

    expect(mcpState.hasPrompts).toBe(true);
    expect(mcpState.promptNames).toContain('swimming_advisor');
    expect(mcpState.promptNames).toContain('daily_rhine_report');
    expect(mcpState.promptNames).toContain('rhine_safety_briefing');

    expect(mcpState.hasResources).toBe(true);
    expect(mcpState.resourceUris).toContain('rhine://basel/current.json');
    expect(mcpState.resourceUris).toContain('rhine://basel/prognosis-logic.md');

    expect(mcpState.tempResultParsed).toBeDefined();
    expect(mcpState.tempResultParsed.waterTemperature.unit).toBe('°C');
  });
});


import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    const bodies: Record<string, unknown> = {
      "/api/me": {
        user: { telegramId: 1, username: "tester", firstName: "Тест" },
      },
      "/api/catalog": {
        providers: Array.from({ length: 12 }, (_, index) => ({
          name: `Source${index + 1}`,
          label: `Source ${index + 1}`,
          pairs: [
            {
              symbol: `P${index + 1}/MNT`,
              label: `Pair ${index + 1}`,
              subscribed: false,
              formulaFields: [{ key: "rate", label: "ханш" }],
            },
          ],
        })),
      },
      "/api/formulas": { formulas: [] },
      "/api/branding": { appLogoUrl: null, sourceLogos: {} },
      "/api/settings": { calculatorMode: "tape" },
      "/api/subscriptions": { subscriptions: [] },
      "/api/rates": { rates: [] },
      "/api/calculated": {
        rates: [
          {
            key: "formula:delcrado",
            kind: "calculated",
            source: "Тооцоолсон",
            pair: "ДЕЛЬКРАДО",
            values: [{ label: "value", amount: "50.25" }],
            details: [],
            fetchedAt: "2026-07-30T08:00:00Z",
            status: "fresh",
            formula: "MongolBank RUB/MNT × 1.005",
          },
        ],
      },
    };
    if (pathname === "/api/calculate") {
      await route.fulfill({ json: {
        expression: "2621878.49 + 5000 × 44.9",
        result: "117946844.201",
        steps: [
          { operator: "+", operand: "2621878.49", subtotal: "2621878.49" },
          { operator: "+", operand: "5000", subtotal: "2626878.49" },
          { operator: "*", operand: "44.9", subtotal: "117946844.201" },
        ],
      } });
      return;
    }
    await route.fulfill({ json: bodies[pathname] || { ok: true } });
  });
});

test("navigates between the four primary areas", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Ханш", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Тооцоолсон" }).last().click();
  await expect(page.getByText("ДЕЛЬКРАДО")).toBeVisible();
  await page.getByRole("button", { name: "Тооны машин" }).last().click();
  await expect(page.getByRole("heading", { name: "Тооны машин" })).toBeVisible();
  await page.getByRole("button", { name: "Тохиргоо" }).last().click();
  await expect(page.getByRole("heading", { name: "Тохиргоо" })).toBeVisible();
});

test("keeps every watchlist source and pair reachable", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Ханш нэмэх" }).click();
  const finalSource = page.getByRole("button", {
    name: "Source 12",
    exact: true,
  });
  await finalSource.scrollIntoViewIfNeeded();
  await finalSource.click();
  await expect(page.getByText("P12/MNT")).toBeVisible();
});

test("prints a left-to-right financial tape", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Тооны машин" }).last().click();
  await page.getByLabel("1-р мөрийн дүн").fill("2621878.49");
  await page.getByRole("button", { name: "+", exact: true }).click();
  await page.getByLabel("2-р мөрийн дүн").fill("5000");
  await page.getByRole("button", { name: "×", exact: true }).click();
  await page.getByLabel("3-р мөрийн дүн").fill("44.9");
  await page.getByRole("button", { name: "=", exact: true }).click();
  await expect(page.getByText("+ 117,946,844.201")).toBeVisible();
});

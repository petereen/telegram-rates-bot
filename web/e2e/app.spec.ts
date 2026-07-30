import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    const bodies: Record<string, unknown> = {
      "/api/me": {
        user: { telegramId: 1, username: "tester", firstName: "Тест" },
      },
      "/api/catalog": { providers: [] },
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

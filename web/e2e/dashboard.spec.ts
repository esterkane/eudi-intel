import { expect, test } from "@playwright/test";

// Phase 6 gate, as a regression suite: all four views render live data and
// every card click-throughs to its primary source.

const VIEWS = [
  { path: "/releases", heading: "Latest Releases & What Changed" },
  { path: "/roadmap", heading: "Roadmap & Planned Work" },
  { path: "/issues", heading: "Open Issues & Feature Requests" },
  { path: "/activity", heading: "Current Activity" },
];

for (const view of VIEWS) {
  test(`${view.path} renders live cards, all linked`, async ({ page }) => {
    await page.goto(view.path);
    await expect(page.getByRole("heading", { level: 1 })).toContainText(
      view.heading
    );
    const cards = page.locator("a.card");
    const count = await cards.count();
    expect(count, `${view.path} must show live data`).toBeGreaterThan(0);
    for (let i = 0; i < count; i++) {
      const href = await cards.nth(i).getAttribute("href");
      expect(href, `card ${i} on ${view.path} lacks href`).toBeTruthy();
      expect(href).toMatch(/^(https?:\/\/|\/)/);
    }
  });
}

test("nav reaches every view", async ({ page }) => {
  await page.goto("/");
  for (const label of [
    "Releases & What Changed",
    "Roadmap",
    "Open Issues",
    "Activity",
    "Drafts",
  ]) {
    await page.getByRole("navigation").getByText(label, { exact: true }).click();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.goto("/");
  }
});

test("what-changed card shows section-level diff stats", async ({ page }) => {
  await page.goto("/releases");
  const diffCard = page.locator("a.card", { hasText: "→" }).first();
  await expect(diffCard).toBeVisible();
  await expect(diffCard.locator(".diff-stats")).toContainText("changed");
});

test("home shows health panel and view links", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "EUDI Intelligence"
  );
  await expect(page.locator(".home-links a.card")).toHaveCount(4);
  await expect(page.locator(".panel")).toBeVisible();
});

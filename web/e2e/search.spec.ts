import { expect, test } from "@playwright/test";

// Search/answer UI: hybrid search results with citations, typo-tolerant
// suggest, tier filter, and the grounded-answer panel.

test("search returns cited results", async ({ page }) => {
  test.setTimeout(240_000); // query-time embed may cold-load BGE-M3
  await page.goto("/search");
  await page.getByLabel("search query").fill("wallet unit attestation");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.locator(".result").first()).toBeVisible({ timeout: 200_000 });
  const first = page.locator(".result").first();
  await expect(first.locator(".citation-line .badge").first()).toBeVisible();
  await expect(first.locator(".citation-line a")).toHaveAttribute(
    "href",
    /https?:\/\//
  );
  await expect(first.locator(".meta").last()).toContainText("score");
});

test("typo suggest offers corrections", async ({ page }) => {
  await page.goto("/search");
  await page.getByLabel("search query").fill("anex 2 high levl requirments");
  await expect(page.locator(".suggest-list button").first()).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.locator(".suggest-list")).toContainText(/high-level/i);
});

test("tier filter constrains results", async ({ page }) => {
  test.setTimeout(240_000);
  await page.goto("/search");
  await page.getByLabel("search query").fill("attestation revocation");
  await page.getByLabel("tier filter").selectOption("normative");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.locator(".result").first()).toBeVisible({ timeout: 200_000 });
  const badges = page.locator(".result .citation-line .badge");
  const count = await badges.count();
  for (let i = 0; i < count; i++) {
    await expect(badges.nth(i)).toHaveText("normative");
  }
});

test("ask produces a grounded answer with citations", async ({ page }) => {
  test.setTimeout(600_000); // full LLM round trip
  await page.goto("/search");
  await page
    .getByLabel("search query")
    .fill("Which credential formats does the reference implementation support?");
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.locator(".answer")).toBeVisible({ timeout: 580_000 });
  await expect(page.locator(".answer h2")).toContainText("Grounded answer");
  await expect(page.locator(".answer .citation-line").first()).toBeVisible();
});

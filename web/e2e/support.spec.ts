import { expect, test } from "@playwright/test";

// S4 support console: fast triage (no generation) returns the structured packet
// — related activity heading + the glossary panel for a recognised term.

test("support console fast triage shows related section and glossary", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await page.goto("/support");
  await page.getByLabel("support query").fill("wallet unit attestation revocation");
  await page.getByRole("button", { name: "Fast (no answer)" }).click();

  // related-activity section always renders (count may vary)
  await expect(page.getByRole("heading", { name: /Related activity/ })).toBeVisible({
    timeout: 90_000,
  });
  // glossary deterministically explains the WUA term
  await expect(page.locator(".glossary-panel")).toContainText(/Wallet Unit Attestation/);
  // no generated answer on the fast path
  await expect(page.getByRole("heading", { name: "Answer", exact: true })).toHaveCount(0);
});

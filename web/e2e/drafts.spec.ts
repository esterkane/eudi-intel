import { expect, test } from "@playwright/test";

// Phase 7 gate, as a regression suite: drafts show per-section provenance and
// publishing requires the explicit finalize action (clicked here through the UI).

const API = process.env.E2E_API_URL ?? "http://localhost:8000";

test("drafts list renders with status badges", async ({ page }) => {
  await page.goto("/drafts");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Authored Drafts"
  );
});

test("draft detail shows provenance and the finalize flow publishes", async ({
  page,
  request,
}) => {
  // creating a draft is an LLM call on the 4060 (cold model reload + possible
  // uncited-retry) — allow generous time, keep the draft small (faq, 2 chunks)
  test.setTimeout(900_000);

  const search = await request.get(
    `${API}/search?q=wallet%20unit%20attestation&limit=2`,
    { timeout: 300_000 }
  );
  expect(search.ok()).toBeTruthy();
  const { results } = (await search.json()) as {
    results: { content: string; citation: Record<string, unknown> }[];
  };
  expect(results.length).toBeGreaterThan(0);

  const created = await request.post(`${API}/author/draft`, {
    data: {
      doc_type: "faq",
      topic: "e2e: wallet unit attestation notes",
      evidence: results.map((r) => ({ content: r.content, citation: r.citation })),
    },
    timeout: 720_000,
  });
  expect(created.ok()).toBeTruthy();
  const draft = (await created.json()) as { id: number; status: string };
  expect(draft.status).toBe("draft"); // never born published

  await page.goto(`/drafts/${draft.id}`);
  await expect(page.locator(".badge", { hasText: "draft" }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Source basis" })).toBeVisible();
  // per-section provenance: at least one citation line with a tier marker
  await expect(page.locator(".meta div").first()).toContainText("[");

  // the explicit human action; the component reloads the page itself, so we
  // avoid all navigation races by polling the API for the status flip and
  // then loading the page fresh
  await page.getByRole("button", { name: /Finalize/ }).click();
  await expect
    .poll(
      async () => {
        const r = await request.get(`${API}/author/draft/${draft.id}`);
        return ((await r.json()) as { status: string }).status;
      },
      { timeout: 60_000 }
    )
    .toBe("published");

  await page.goto(`/drafts/${draft.id}`);
  await expect(
    page.locator(".badge", { hasText: "published" }).first()
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /Finalize/ })).toHaveCount(0);
});

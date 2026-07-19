import { expect, test } from "@playwright/test";

/**
 * Browser-level E2E against the mocked backend (src/run_mock_api.py):
 * the exact flow that unit tests can't cover — stream rendering, citation
 * chips, and the PDF panel opening. Would have caught the CORS-redirect bug.
 */

test("ask → streamed answer → citation chip → PDF panel", async ({ page }) => {
  await page.goto("/");

  // Greeting empty state renders
  await expect(page.getByText("Hello, researcher")).toBeVisible();

  // Ask a question
  const input = page.getByPlaceholder(/Ask Corpus/);
  await input.fill("What is the complexity of attention?");
  await input.press("Enter");

  // Streamed tokens render into an assistant message
  await expect(page.locator(".prose-answer").first()).toBeVisible({ timeout: 30_000 });

  // A citation chip arrives with the stream
  const chip = page.getByText(/PDF\s*1/).first();
  await expect(chip).toBeVisible({ timeout: 30_000 });

  // Clicking it opens the PDF viewer panel (header shows the paper title)
  await chip.click();
  await expect(page.getByLabel("Close PDF")).toBeVisible({ timeout: 10_000 });
});

test("library lists mock papers", async ({ page }) => {
  await page.goto("/library");
  await expect(page.getByText(/papers indexed/)).toBeVisible({ timeout: 15_000 });
});

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

/** Starts a short run against the demo target through the API and waits for it to end. */
async function createRun(
  request: APIRequestContext,
  name: string,
  load: Record<string, unknown> = { vus: 2, duration: 1.2 },
): Promise<string> {
  const resp = await request.post("/api/runs", {
    data: { name, request: { url: "http://127.0.0.1:8099/demo/random-latency?min_ms=5&max_ms=30" }, load },
  });
  expect(resp.status(), await resp.text()).toBe(201);
  const { id } = (await resp.json()) as { id: string };
  await expect
    .poll(async () => ((await (await request.get(`/api/runs/${id}`)).json()) as { ended_at: number | null }).ended_at, {
      timeout: 15_000,
    })
    .not.toBeNull();
  return id;
}

function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => msg.type() === "error" && errors.push(msg.text()));
  page.on("pageerror", (err) => errors.push(err.message));
  return errors;
}

test("history lists, searches, compares and deletes runs", async ({ page, request }) => {
  const errors = collectConsoleErrors(page);
  const a = await createRun(request, "e2e checkout");
  const b = await createRun(request, "e2e checkout", { vus: 4, duration: 1.2 });
  await createRun(request, "e2e login");

  await page.goto("/history");
  const table = page.getByRole("table", { name: "Saved runs" });
  await expect(table.getByRole("link", { name: "e2e checkout" })).toHaveCount(2);

  await page.getByLabel("Search by name").fill("e2e checkout");
  await expect(table.getByRole("link", { name: "e2e login" })).toHaveCount(0);
  await expect(table.getByRole("link", { name: "e2e checkout" })).toHaveCount(2);

  // Compare needs at least two selections.
  const compare = page.getByRole("button", { name: /Compare selected/ });
  await expect(compare).toBeDisabled();
  await page.getByRole("checkbox").nth(0).check();
  await page.getByRole("checkbox").nth(1).check();
  await expect(compare).toHaveText("Compare selected (2)");
  await compare.click();

  await expect(page).toHaveURL(/\/compare\?ids=/);
  await expect(page.getByRole("heading", { name: "Compare 2 runs" })).toBeVisible();
  const cmp = page.getByRole("table", { name: "Comparison" });
  await expect(cmp.getByRole("row", { name: /p95 latency/ })).toBeVisible();
  await expect(cmp).toContainText("Reference");
  await expect(page.locator(".chart canvas")).toHaveCount(2);

  // Delete one from History with the confirm dialog; Escape cancels, the button confirms.
  await page.getByRole("link", { name: "Back to History" }).click();
  await page.getByLabel("Search by name").fill("e2e login");
  await expect(table.getByRole("link", { name: "e2e login" })).toHaveCount(1);
  await page.getByRole("checkbox").first().check();
  await page.getByRole("button", { name: "Delete selected" }).click();
  const dialog = page.getByRole("dialog", { name: "Delete 1 run?" });
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await page.getByRole("button", { name: "Delete selected" }).click();
  await dialog.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByText("No runs match “e2e login”.")).toBeVisible();

  expect([a, b]).toHaveLength(2);
  expect(errors).toEqual([]);
});

test("baseline, notes, compare with baseline and run again", async ({ page, request }) => {
  const errors = collectConsoleErrors(page);
  const base = await createRun(request, "e2e baseline flow");
  const next = await createRun(request, "e2e baseline flow", { rate: 15, duration: 1.2 });

  await page.goto(`/runs/${base}`);
  await page.getByRole("button", { name: "Mark as baseline" }).click();
  await expect(page.getByRole("button", { name: "Remove as baseline" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".run-title")).toContainText("Baseline");

  await page.getByLabel("Notes").fill("before adding the cache");
  await page.getByRole("button", { name: "Save notes" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Saved." })).toBeVisible();

  // The other run offers a comparison against the baseline.
  await page.goto(`/runs/${next}`);
  await page.getByRole("link", { name: "Compare with baseline" }).click();
  await expect(page).toHaveURL(new RegExp(`/compare\\?ids=${base},${next}`));
  await expect(page.getByText(/the baseline\./)).toBeVisible();

  // Notes persisted.
  await page.goto(`/runs/${base}`);
  await expect(page.getByLabel("Notes")).toHaveValue("before adding the cache");

  // Run again fills the form from the saved plan.
  await page.goto(`/runs/${next}`);
  await page.getByRole("button", { name: "Run again" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByText("Filled in from “e2e baseline flow”")).toBeVisible();
  await expect(page.getByRole("radio", { name: "Requests per second" })).toBeChecked();
  await expect(page.getByLabel("Target rate (req/s)")).toHaveValue("15");
  await expect(page.getByLabel("URL")).toHaveValue(/demo\/random-latency/);

  expect(errors).toEqual([]);
});

test("safety limits block oversized tests and live changes", async ({ page, request }) => {
  await page.goto("/settings");
  await page.getByLabel("Max virtual users").fill("20");
  await page.getByLabel("Max requests per second").fill("50");
  await page.getByLabel("Max test length").fill("1m");
  await page.getByRole("button", { name: "Save limits" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Saved." })).toBeVisible();

  // The form checks the limits before sending.
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "New test" }).click();
  await page.getByLabel("URL").fill("http://127.0.0.1:8099/demo/fast");
  await page.getByLabel("Number of users").fill("25");
  await expect(page.getByText("Limit: 20")).toBeVisible();
  await page.getByRole("button", { name: "Start test" }).click();
  await expect(page.getByText("The limit is 20 users (change it in Settings).")).toBeVisible();

  // The server enforces them too, including for live changes.
  const resp = await request.post("/api/runs", {
    data: { request: { url: "http://127.0.0.1:8099/demo/fast" }, load: { vus: 25, duration: 5 } },
  });
  expect(resp.status()).toBe(400);

  await page.getByLabel("Number of users").fill("2");
  await page.getByLabel("Duration").fill("20s");
  await page.getByRole("button", { name: "Start test" }).click();
  await expect(page.locator(".run-title .status")).toHaveText("Running");
  await page.getByLabel("Target users", { exact: true }).fill("30");
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page.getByRole("alert")).toContainText("The safety limit is 20 users");
  await page.getByRole("button", { name: "Abort" }).click();
  await expect(page.locator(".run-title .status")).toHaveText("Aborted");

  // Restore defaults for other tests.
  await request.put("/api/settings", { data: { limits: { max_vus: 1000, max_rate: 5000, max_duration: 7200 } } });
});

test("settings validate input", async ({ page }) => {
  await page.goto("/settings");
  await page.getByLabel("Max virtual users").fill("0");
  await page.getByLabel("Max test length").fill("soon");
  await page.getByRole("button", { name: "Save limits" }).click();
  await expect(page.getByText("Enter a whole number, 1 or more.")).toBeVisible();
  await expect(page.getByText("Use a duration like 30m or 2h.")).toBeVisible();
});

test("compare page explains how to start", async ({ page }) => {
  await page.goto("/compare");
  await expect(page.getByText("Pick 2 to 4 runs in History to compare them.")).toBeVisible();
  await page.getByRole("link", { name: "Open History" }).click();
  await expect(page.getByRole("heading", { name: "History" })).toBeVisible();
});

test.describe("mobile", () => {
  test.use({ viewport: { width: 375, height: 740 } });

  test("history and compare fit the screen", async ({ page, request }) => {
    const a = await createRun(request, "e2e mobile");
    const b = await createRun(request, "e2e mobile");
    for (const path of ["/history", `/compare?ids=${a},${b}`, "/settings"]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, path).toBeLessThanOrEqual(0);
    }
  });
});

import { expect, test, type Page } from "@playwright/test";

function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => msg.type() === "error" && errors.push(msg.text()));
  page.on("pageerror", (err) => errors.push(err.message));
  return errors;
}

async function noHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

test("run a demo test from the browser and control it live", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  await page.goto("/");

  await page.getByRole("button", { name: /built-in demo target/ }).click();
  // Users click the visible label; the native radio inside it is visually hidden.
  await page.locator(".segmented label", { hasText: "Requests per second" }).click();
  await expect(page.getByRole("radio", { name: "Requests per second" })).toBeChecked();
  await page.getByLabel("Target rate (req/s)").fill("30");
  await page.getByLabel("Duration").fill("40s");
  await page.getByRole("button", { name: "Start test" }).click();

  await expect(page).toHaveURL(/\/runs\/[0-9a-f]+$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Demo: random latency");
  await expect(page.locator(".run-title .status")).toHaveText("Running");

  // Charts appear after the first full second of data.
  await expect(page.locator(".chart canvas")).toHaveCount(4, { timeout: 5000 });
  await expect(page.locator(".metric").filter({ hasText: "Requests" }).last().locator("dd").first())
    .not.toHaveText("0", { timeout: 5000 });

  // Change the load mid-run.
  await page.getByLabel("Target requests per second", { exact: true }).fill("60");
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page.locator(".metric").filter({ hasText: "Requests/s" }).locator(".metric-note"))
    .toHaveText("target 60.0");

  await page.getByRole("button", { name: "Pause" }).click();
  await expect(page.locator(".run-title .status")).toHaveText("Paused");
  await page.getByRole("button", { name: "Resume" }).click();
  await expect(page.locator(".run-title .status")).toHaveText("Running");

  await page.getByRole("button", { name: "Stop" }).click();
  await expect(page.locator(".run-title .status")).toHaveText("Finished", { timeout: 15_000 });

  // Finished view: controls are gone, results are summarised.
  await expect(page.getByRole("button", { name: "Pause" })).toHaveCount(0);
  await expect(page.getByRole("table", { name: "Results per step" })).toContainText("request");
  await expect(page.getByText("Status codes")).toBeVisible();
  await expect(page.locator(".code-list")).toContainText("200");

  // The run is listed on the home page.
  await page.getByRole("link", { name: "Start another test" }).click();
  await expect(page.locator(".run-list")).toContainText("Demo: random latency");

  expect(errors).toEqual([]);
});

test("shows validation errors without starting a run", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("URL").fill("not a url");
  await page.getByLabel("Number of users").fill("0");
  await page.getByRole("button", { name: "Start test" }).click();
  await expect(page.getByText("The URL must start with http:// or https://.")).toBeVisible();
  await expect(page.getByText("Enter how many users, 1 or more.")).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("Fix the 2 highlighted fields");
  await expect(page).toHaveURL(/\/$/);
});

test("theme toggle switches and persists", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: "Light theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: "Dark theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("unknown run and unknown page show helpful states", async ({ page }) => {
  await page.goto("/runs/doesnotexist");
  await expect(page.getByRole("heading", { name: "Run not found" })).toBeVisible();
  await page.getByRole("link", { name: "Start a new test" }).click();
  await expect(page.getByRole("heading", { name: "New test" })).toBeVisible();

  await page.goto("/nowhere");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
});

test("form is usable with the keyboard", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByLabel("URL")).toBeFocused();
  await page.keyboard.type("http://127.0.0.1:1/");
  await page.keyboard.press("Shift+Tab");
  await expect(page.getByLabel("Method")).toBeFocused();
  // Radios in the load-model group are reachable and switch with arrow keys.
  await page.getByRole("radio", { name: "Virtual users" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("radio", { name: "Requests per second" })).toBeChecked();
});

test.describe("mobile", () => {
  test.use({ viewport: { width: 375, height: 740 } });

  test("no horizontal overflow on the form and run pages", async ({ page }) => {
    await page.goto("/");
    await noHorizontalOverflow(page);
    await page.getByText("Headers, body and timeout").click();
    await page.getByText("Run options").click();
    await noHorizontalOverflow(page);

    await page.getByRole("button", { name: /built-in demo target/ }).click();
    await page.getByLabel("Duration").fill("3s");
    await page.getByLabel("Number of users").fill("2");
    await page.getByRole("button", { name: "Start test" }).click();
    await expect(page.locator(".chart canvas")).toHaveCount(4, { timeout: 5000 });
    await noHorizontalOverflow(page);
    await expect(page.locator(".run-title .status")).toHaveText("Finished", { timeout: 15_000 });
    await noHorizontalOverflow(page);
  });
});

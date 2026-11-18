import { expect, Page, test } from "@playwright/test";

async function persona(page: Page, name: string) {
  await page.goto("/login");
  await page.getByRole("button", { name: new RegExp(name, "i") }).click();
  await expect(page).toHaveURL(/dashboard/);
}

const nav = (page: Page, name: string) =>
  page.getByRole("navigation", { name: "Primary navigation" }).getByRole("link", { name, exact: true });

test("plan is authored, approved as a package, activated for a cohort and released to students", async ({ page }) => {
  test.setTimeout(90_000);
  const stamp = Date.now().toString().slice(-6);
  const label = `9.${stamp}`;
  const code = `CH-E2E-${stamp}`;

  // 1. Curriculum editor clones the approved plan, adds an investigator-only challenge, submits.
  await persona(page, "Sam Ortega");
  await nav(page, "Scenarios").click();
  await page.getByRole("button", { name: /HARBORLINE v0\.5/ }).click();
  await expect(page.getByText("Answer key").first()).toBeVisible();
  await page.getByPlaceholder("New version label, e.g. 1.1").fill(label);
  await page.getByRole("button", { name: "Clone to new version" }).click();
  await expect(page.getByText(`Version ${label} created as an editable draft.`)).toBeVisible();
  await page.getByRole("button", { name: "Add item" }).click();
  await page.getByLabel("Item code").fill(code);
  await page.getByLabel("Title").fill("E2E evidence triage");
  await page.getByLabel("Audience").selectOption("investigator");
  await page.getByLabel("Time limit (minutes, optional)").fill("10");
  await page.getByLabel("Content students will see").fill("List the two records most at risk of loss.");
  await page.getByRole("button", { name: "Add item", exact: true }).last().click();
  await expect(page.getByText("Item added.")).toBeVisible();
  await page.getByRole("button", { name: "Submit for approval" }).click();
  await expect(page.getByText(/Submitted for approval/)).toBeVisible();

  // 2. Content approver approves the whole plan; it locks.
  await persona(page, "Dana Whitfield");
  await nav(page, "Scenarios").click();
  await page.getByRole("button", { name: new RegExp(`HARBORLINE v${label.replace(".", "\\.")}`) }).click();
  await page.getByRole("button", { name: "Approve release plan" }).click();
  await expect(page.getByText("Release plan approved and locked.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Add item" })).toHaveCount(0);

  // 3. Program administrator creates a cohort, activates the version and enrolls an investigator.
  await persona(page, "Jamie Novak");
  await nav(page, "Cohorts").click();
  const cohort = `E2E-PLAN-${stamp}`;
  await page.getByLabel("Code").fill(cohort);
  await page.getByLabel("Name").fill(`Release plan ${stamp}`);
  await page.getByLabel("Start").fill("2026-01-12");
  await page.getByLabel("End").fill("2026-01-16");
  await page.getByRole("button", { name: "Create cohort" }).click();
  await expect(page.getByRole("heading", { name: `Release plan ${stamp}` })).toBeVisible();
  await page.getByLabel("Approved scenario version").selectOption({ label: `HARBORLINE v${label}` });
  await page.getByRole("button", { name: "Activate scenario" }).click();
  await expect(page.getByText(`Running HARBORLINE v${label}`)).toBeVisible();
  await page.getByRole("combobox", { name: "User", exact: true }).selectOption({ label: "Drew Patel (inv.patel)" });
  await page.getByLabel("Assessed pathway").selectOption("investigator");
  await page.getByRole("button", { name: "Add to cohort" }).click();
  await expect(page.getByRole("row", { name: /Drew Patel/ })).toBeVisible();

  // 4. Release the challenge from the release plan.
  await nav(page, "Release Plan").click();
  await page.getByRole("combobox", { name: "Cohort", exact: true }).selectOption({ label: `${cohort} — Release plan ${stamp}` });
  const row = page.getByRole("row", { name: new RegExp(code) });
  await expect(row.getByText("pending")).toBeVisible();
  await expect(page.getByRole("row", { name: /CH-K01/ }).getByText(/Blocked: Scored use of K01/)).toBeVisible();
  await row.getByRole("button", { name: "Release now" }).click();
  await expect(page.getByText(`${code}: released.`)).toBeVisible();
  await page.screenshot({ path: "test-results/release-plan-timeline.png", fullPage: true });

  // 5. The investigator sees it; the answer key never appears.
  await persona(page, "Drew Patel");
  await nav(page, "Challenges").click();
  await expect(page.getByRole("heading", { name: "E2E evidence triage" })).toBeVisible();
  await expect(page.getByText("10 minutes")).toBeVisible();
  await expect(page.getByText(/Answer notes/)).toHaveCount(0);

  // Clean up the persona's extra enrollment so repeated runs do not accumulate.
  await persona(page, "Jamie Novak");
  await nav(page, "Cohorts").click();
  await page.getByRole("button", { name: new RegExp(cohort) }).click();
  await page.getByRole("row", { name: /Drew Patel/ }).getByRole("button", { name: "Withdraw" }).click();
  await expect(page.getByText("Member withdrawn. Their records are kept.")).toBeVisible();
});

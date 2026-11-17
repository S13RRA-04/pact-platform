import { expect, Page, test } from "@playwright/test";

/** Every sidebar page must load for every kind of account without an uncaught error.
 * Regression for "Forbidden" crashes when non-students opened student-only pages. */
const ROLES: [string, string][] = [
  ["Taylor Brooks", "student"],
  ["Casey Lin", "instructor"],
  ["Jamie Novak", "program administrator"],
  ["Avery Kim", "security/operations administrator"],
  ["Sam Ortega", "curriculum editor"],
];

async function signIn(page: Page, name: string) {
  await page.goto("/login");
  await page.getByRole("button", { name: new RegExp(name, "i") }).click();
  await expect(page).toHaveURL(/dashboard/);
}

for (const [name, role] of ROLES) {
  test(`every sidebar page loads for a ${role}`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(`${page.url()}: ${e.message}`));
    await signIn(page, name);
    const nav = page.getByRole("navigation", { name: "Primary navigation" });
    await expect(nav.getByRole("link").first()).toBeVisible();
    const hrefs = await nav.getByRole("link").evaluateAll((links) => links.map((a) => a.getAttribute("href")!));
    for (const href of hrefs) {
      await page.goto(href);
      await page.waitForLoadState("networkidle");
      await expect(page.getByText("This page couldn’t load")).toHaveCount(0);
    }
    expect(errors).toEqual([]);
  });
}

test("non-students get a staff workspace and no student-only links", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await signIn(page, "Jamie Novak");
  await expect(page.getByRole("heading", { name: "Your workspace" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Cohorts and enrollment" })).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Primary navigation" });
  await expect(nav.getByRole("link", { name: "Assessments" })).toHaveCount(0);
  await expect(nav.getByRole("link", { name: "Case Center" })).toHaveCount(0);
  // Opening student-only pages directly explains instead of crashing.
  await page.goto("/assessments");
  await expect(page.getByText("available to enrolled students only")).toBeVisible();
  await page.goto("/case");
  await expect(page.getByText("not a member of any cohort")).toBeVisible();
  expect(errors).toEqual([]);
});

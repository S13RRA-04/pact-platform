import { createHmac } from "node:crypto";
import { expect, Page, test } from "@playwright/test";

/** RFC 6238 TOTP (SHA-1, 30 s, 6 digits) so the test can act as the user's authenticator app. */
function totp(base32: string, offsetSeconds = 0): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const ch of base32.replace(/[\s=]/g, "").toUpperCase()) bits += alphabet.indexOf(ch).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor((Date.now() / 1000 + offsetSeconds) / 30)));
  const mac = createHmac("sha1", key).update(counter).digest();
  const offset = mac[mac.length - 1] & 0xf;
  return String((mac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

async function persona(page: Page, name: string) {
  await page.goto("/login");
  await page.getByRole("button", { name: new RegExp(name, "i") }).click();
  await expect(page).toHaveURL(/dashboard/);
}

async function signOut(page: Page) {
  // Via the Account page: the sidebar control is hidden on narrow (mobile) layouts.
  await page.goto("/account");
  await page.locator("main").getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/login/);
}

const PASSWORD = "evening tide over the harbor 7";

test("admin onboards a user who signs in with password and authenticator, then enrolls them", async ({ page }) => {
  const stamp = Date.now().toString().slice(-7);
  const username = `e2e.analyst${stamp}`;
  const displayName = `E2E Analyst ${stamp}`;

  // 1. Program Administrator creates the account and issues a one-time setup link.
  await persona(page, "Jamie Novak");
  await page.getByRole("navigation", { name: "Primary navigation" }).getByRole("link", { name: "Users", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Users and access" })).toBeVisible();
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Display name").fill(displayName);
  await page.getByLabel("Email").fill(`${username}@pact-training.example`);
  await page.getByRole("button", { name: "Create user" }).click();
  const row = page.getByRole("row", { name: new RegExp(displayName) });
  await expect(row.getByText("Not set up")).toBeVisible();
  await row.getByRole("button", { name: "Issue setup link" }).click();
  const link = (await page.locator(".secret-box").first().textContent())!.trim();
  expect(link).toContain("/setup#token=");
  await signOut(page);

  // 2. The user opens the link, enrolls an authenticator and sets a password.
  await page.goto(link);
  await expect(page.getByRole("heading", { name: `Welcome, ${displayName}` })).toBeVisible();
  expect(page.url()).not.toContain("token="); // removed from the address bar once read
  const secret = (await page.getByLabel("Authenticator setup key").textContent())!;
  await page.getByLabel("New password").fill(PASSWORD);
  await page.getByLabel("Confirm password").fill(PASSWORD);
  await page.getByLabel("Current 6-digit code").fill(totp(secret));
  await page.getByRole("button", { name: "Activate account" }).click();
  await expect(page.getByRole("heading", { name: "Your account is ready" })).toBeVisible();

  // 3. Two-step sign-in. A wrong password is refused with a generic message.
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill("not the password at all");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.locator(".error[role=alert]")).toContainText("Sign-in failed");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "Enter your authenticator code" })).toBeVisible();
  // The enrollment code used the current 30 s step; the next step is accepted and single-use.
  await page.getByLabel("Authenticator code").fill(totp(secret, 30));
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/dashboard/);
  await page.goto("/account");
  await expect(page.getByRole("heading", { name: displayName })).toBeVisible();
  await page.locator("main").getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/login/);
  await page.goto("/account");
  await expect(page).toHaveURL(/login/); // session really ended

  // 4. Administrator creates a cohort, enrolls the user as an analyst and places them in a squad.
  await persona(page, "Jamie Novak");
  await page.getByRole("navigation", { name: "Primary navigation" }).getByRole("link", { name: "Cohorts", exact: true }).click();
  const code = `E2E-${stamp}`;
  await page.getByLabel("Code").fill(code);
  await page.getByLabel("Name").fill(`E2E cohort ${stamp}`);
  await page.getByLabel("Start").fill("2027-02-01");
  await page.getByLabel("End").fill("2027-02-05");
  await page.getByRole("button", { name: "Create cohort" }).click();
  await expect(page.getByRole("heading", { name: `E2E cohort ${stamp}` })).toBeVisible();
  // The code can be corrected after creation; an existing code is refused and the form stays open.
  await page.getByRole("button", { name: "Edit details" }).click();
  await page.getByLabel("Cohort code").fill("PACT-DEMO-01");
  await page.getByRole("button", { name: "Save details" }).click();
  await expect(page.locator(".error[role=alert]")).toContainText("already exists");
  await page.getByLabel("Cohort code").fill(`E2E-R${stamp}`);
  await page.getByRole("button", { name: "Save details" }).click();
  await expect(page.getByText("Cohort details saved.")).toBeVisible();
  await expect(page.locator(".eyebrow", { hasText: `E2E-R${stamp}` })).toBeVisible();
  await expect(page.getByRole("button", { name: new RegExp(`E2E-R${stamp}`) })).toBeVisible(); // cohort list
  await page.getByRole("combobox", { name: "User", exact: true }).selectOption({ label: `${displayName} (${username})` });
  await page.getByLabel("Cohort role").selectOption("student");
  await page.getByLabel("Assessed pathway").selectOption("analyst");
  await page.getByRole("button", { name: "Add to cohort" }).click();
  await expect(page.getByRole("row", { name: new RegExp(displayName) })).toBeVisible();
  await page.getByPlaceholder("New squad name").fill("Delta");
  await page.getByRole("button", { name: "Add squad" }).click();
  await page.getByLabel("Add a student to Delta").selectOption({ label: `${displayName} (analyst)` });
  await expect(page.getByRole("button", { name: `Remove ${displayName} from Delta` })).toBeVisible();
  await page.screenshot({ path: "test-results/accounts-cohort-admin.png", fullPage: true });
});

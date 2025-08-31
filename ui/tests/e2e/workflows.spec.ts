import { test, expect } from "@playwright/test";
import { TestUtils } from "./utils/test-utils";

test.describe("Chat Flow Tests", () => {
  let utils: TestUtils;

  test.beforeEach(async ({ page }) => {
    utils = new TestUtils(page);
    await utils.mockAPI();
  });

  test("complete chat workflow", async ({ page }) => {
    // Login
    await utils.login();
    await utils.assertAuthenticated();

    // Wait for models and select one
    await utils.waitForModelsLoaded();
    await utils.selectModel("gpt 5");

    // Send a message
    await utils.sendMessage("Hello, how are you?");

    // Verify message appears
    await expect(
      page.locator(".bg-blue-600").locator("text=Hello, how are you?"),
    ).toBeVisible();

    // Verify typing indicator appears
    await expect(page.locator("text=AI is thinking...")).toBeVisible();

    // Logout
    await page.click('button:has-text("Logout")');
    await utils.assertNotAuthenticated();
  });

  test("error handling workflow", async ({ page }) => {
    // Mock network error for login
    await utils.mockNetworkError("**/auth/login");

    await page.goto("/login");
    await page.fill('input[type="text"]', "admin");
    await page.fill('input[type="password"]', "admin");
    await page.click('button[type="submit"]');

    // Should show connection error
    await expect(page.locator(".text-red-700")).toContainText(
      "connection error",
    );
  });

  test("accessibility workflow", async ({ page }) => {
    await page.goto("/login");

    // Check accessibility
    await utils.checkAccessibility();

    // Test keyboard navigation
    await utils.testKeyboardNavigation([
      'input[type="text"]',
      'input[type="password"]',
      'button[type="submit"]',
    ]);
  });

  test("responsive design workflow", async ({ page }) => {
    // Test mobile
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto("/login");
    await expect(page.locator('input[type="text"]')).toBeVisible();

    // Test tablet
    await page.setViewportSize({ width: 768, height: 1024 });
    await expect(page.locator('input[type="text"]')).toBeVisible();

    // Test desktop
    await page.setViewportSize({ width: 1920, height: 1080 });
    await expect(page.locator('input[type="text"]')).toBeVisible();
  });

  test.skip("session persistence workflow", async ({ page }) => {
    // Skip until authentication is properly implemented
    // Login
    await utils.login();
    await utils.assertAuthenticated();

    // Reload page
    await page.reload();

    // Should redirect to login (since we're using mocked session)
    await utils.assertNotAuthenticated();
  });

  test("multiple messages workflow", async ({ page }) => {
    await utils.mockAuth();
    await page.goto("/app");

    // Send multiple messages
    const messages = ["Message 1", "Message 2", "Message 3"];

    for (const message of messages) {
      await utils.sendMessage(message);
      await expect(
        page.locator(`.bg-blue-600:has-text("${message}")`),
      ).toBeVisible();
    }

    // All messages should be visible
    for (const message of messages) {
      await expect(
        page.locator(`.bg-blue-600:has-text("${message}")`),
      ).toBeVisible();
    }
  });
});

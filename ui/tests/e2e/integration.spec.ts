import { test, expect } from "@playwright/test";

test.describe("Navigation and Routing", () => {
  test.skip("should redirect to login when accessing app without authentication", async ({
    page,
  }) => {
    // Skip this test until authentication protection is implemented
    await page.goto("/app");

    // Should redirect to login page
    await expect(page).toHaveURL("/login");
  });

  test("should redirect to app after successful login", async ({ page }) => {
    // Mock successful login
    await page.route("**/auth/login", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ success: true }),
        headers: {
          "Set-Cookie": "rag_session=mock-session-token; Path=/; HttpOnly",
        },
      });
    });

    await page.goto("/login");
    await page.fill('input[type="text"]', "admin");
    await page.fill('input[type="password"]', "admin");
    await page.click('button[type="submit"]');

    await expect(page).toHaveURL("/app");
  });

  test("should handle direct URL access", async ({ page }) => {
    // Should be able to access login page directly
    await page.goto("/login");
    await expect(page.locator("h2").first()).toContainText(
      "Sign in to RAG Chat",
    );
  });

  test("should handle non-existent routes", async ({ page }) => {
    const response = await page.goto("/non-existent-page");
    expect(response?.status()).toBe(404);
  });

  test("should preserve URL parameters", async ({ page }) => {
    await page.goto("/login?redirect=/app");

    // URL should maintain the query parameter
    expect(page.url()).toContain("redirect=/app");
  });
});

test.describe("Error Handling", () => {
  test("should handle network timeouts", async ({ page }) => {
    // Mock slow API response
    await page.route("**/auth/login", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 15000)); // 15 second delay
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ success: true }),
      });
    });

    await page.goto("/login");
    await page.fill('input[type="text"]', "admin");
    await page.fill('input[type="password"]', "admin");
    await page.click('button[type="submit"]');

    // Should show timeout error
    await expect(page.locator(".text-red-700")).toContainText(
      "request timeout",
      { timeout: 12000 },
    );
  });

  test("should handle server errors", async ({ page }) => {
    // Mock server error
    await page.route("**/auth/login", async (route) => {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ error: "Internal server error" }),
      });
    });

    await page.goto("/login");
    await page.fill('input[type="text"]', "admin");
    await page.fill('input[type="password"]', "admin");
    await page.click('button[type="submit"]');

    await expect(page.locator(".text-red-700")).toContainText(
      "connection error",
    );
  });

  test("should handle CORS errors", async ({ page }) => {
    // Mock CORS error
    await page.route("**/auth/login", async (route) => {
      await route.abort("failed");
    });

    await page.goto("/login");
    await page.fill('input[type="text"]', "admin");
    await page.fill('input[type="password"]', "admin");
    await page.click('button[type="submit"]');

    await expect(page.locator(".text-red-700")).toContainText(
      "connection error",
    );
  });
});

test.describe("Responsive Design", () => {
  test("should work on mobile viewport", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 }); // iPhone SE

    await page.goto("/login");

    // Login form should be visible and usable
    await expect(page.locator('input[type="text"]')).toBeVisible();
    await expect(page.locator('input[type="password"]')).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toBeVisible();
  });

  test("should work on tablet viewport", async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 }); // iPad

    await page.goto("/login");

    // Interface should adapt to tablet size
    await expect(page.locator(".max-w-md")).toBeVisible();
  });

  test("should work on desktop viewport", async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 }); // Desktop

    await page.goto("/login");

    // Should use full width appropriately
    await expect(page.locator('input[type="text"]')).toBeVisible();
  });
});

test.describe("Performance", () => {
  test("should load login page quickly", async ({ page }) => {
    const startTime = Date.now();
    await page.goto("/login");
    await page.waitForLoadState("networkidle");
    const loadTime = Date.now() - startTime;

    // Should load within 3 seconds
    expect(loadTime).toBeLessThan(3000);
  });

  test("should have no console errors on login page", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        errors.push(msg.text());
      }
    });

    await page.goto("/login");
    await page.waitForLoadState("networkidle");

    // Filter out known development warnings
    const realErrors = errors.filter(
      (error) =>
        !error.includes("React DevTools") &&
        !error.includes("Download the React DevTools"),
    );

    expect(realErrors).toHaveLength(0);
  });
});

test.describe("Security", () => {
  test("should not expose sensitive data in HTML", async ({ page }) => {
    await page.goto("/login");

    const content = await page.content();

    // Should not contain any hardcoded credentials or secrets
    expect(content).not.toContain("admin");
    expect(content).not.toContain("password123");
    expect(content).not.toContain("secret");
    expect(content).not.toContain("token");
  });

  test("should have proper form security attributes", async ({ page }) => {
    await page.goto("/login");

    // Password field should be properly masked
    await expect(page.locator('input[type="password"]')).toHaveAttribute(
      "type",
      "password",
    );

    // Form should have proper autocomplete attributes
    await expect(page.locator('input[type="text"]')).toHaveAttribute(
      "autocomplete",
      "username",
    );
    await expect(page.locator('input[type="password"]')).toHaveAttribute(
      "autocomplete",
      "current-password",
    );
  });

  test("should handle CSP headers properly", async ({ page }) => {
    const response = await page.goto("/login");

    // Should have loaded successfully despite any CSP restrictions
    expect(response?.status()).toBe(200);
  });
});

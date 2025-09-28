import { test, expect, Page } from "@playwright/test";

const waitForLoginHydration = async (page: Page) => {
  const container = page.locator('[data-testid="login-form"]');
  await container.waitFor();
  await expect(container).toHaveAttribute("data-hydrated", "true");
};

test.describe("Login Page", () => {
  test.beforeEach(async ({ page }) => {
    // Mock all API endpoints
    await page.route("http://localhost:8000/**", async (route) => {
      const url = route.request().url();

      if (url.includes("/auth/login")) {
        const request = route.request();
        const body = JSON.parse(request.postData() || "{}");

        if (body.username === "admin" && body.password === "admin") {
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({ ok: true }),
            headers: {
              "Set-Cookie": "rag_session=mock-session-token; Path=/; HttpOnly",
            },
          });
        } else if (body.username === "rate-limited") {
          await route.fulfill({
            status: 429,
            contentType: "application/json",
            body: JSON.stringify({ detail: "too_many_attempts" }),
          });
        } else {
          await route.fulfill({
            status: 401,
            contentType: "application/json",
            body: JSON.stringify({ detail: "invalid_credentials" }),
          });
        }
      } else if (url.includes("/models")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            { id: "gpt-5", label: "gpt 5" },
            { id: "gpt-5-mini", label: "gpt5 mini" },
          ]),
        });
      } else {
        // Default success response for any other API calls
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ok: true }),
        });
      }
    });

    await page.goto("/login");
    await waitForLoginHydration(page);
  });

  test("should display login form", async ({ page }) => {
    await expect(page.locator("h2").first()).toContainText(
      "Sign in to RAG Chat",
    );
    await expect(page.locator('input[type="text"]')).toBeVisible();
    await expect(page.locator('input[type="password"]')).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toContainText(
      "Sign in",
    );
  });

  test("should show validation for empty fields", async ({ page }) => {
    const submitButton = page.locator('button[type="submit"]');
    await expect(submitButton).toBeDisabled();
  });

  test("should enable submit button when fields are filled", async ({
    page,
  }) => {
    await page.fill('input[type="text"]', "admin");
    await page.fill('input[type="password"]', "admin");

    const submitButton = page.locator('button[type="submit"]');
    await expect(submitButton).toBeEnabled();
  });

  test("should login successfully with valid credentials", async ({ page }) => {
    await page.fill('input[type="text"]', "admin");
    await page.fill('input[type="password"]', "admin");
    await page.click('button[type="submit"]');

    // Should redirect to app page
    await expect(page).toHaveURL("/app");
  });

  test("should show error for invalid credentials", async ({ page }) => {
    await page.fill('input[type="text"]', "wrong");
    await page.fill('input[type="password"]', "wrong");
    await page.click('button[type="submit"]');

    await expect(page.locator(".text-red-700")).toContainText(
      "invalid credentials",
    );
  });

  test("should show rate limit error", async ({ page }) => {
    await page.fill('input[type="text"]', "rate-limited");
    await page.fill('input[type="password"]', "password");
    await page.click('button[type="submit"]');

    await expect(page.locator(".text-red-700")).toContainText(
      "too many attempts",
    );
  });

  test("should show loading state during login", async ({ page }) => {
    // Delay the login response to test loading state
    await page.route("**/auth/login", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ success: true }),
      });
    });

    await page.fill('input[type="text"]', "admin");
    await page.fill('input[type="password"]', "admin");
    await page.click('button[type="submit"]');

    // Should show loading state
    await expect(page.locator('button[type="submit"]')).toContainText(
      "Signing in...",
    );
    await expect(page.locator(".animate-spin")).toBeVisible();
  });

  test("should have proper accessibility attributes", async ({ page }) => {
    await expect(page.locator('input[type="text"]')).toHaveAttribute(
      "id",
      "username",
    );
    await expect(page.locator('input[type="password"]')).toHaveAttribute(
      "id",
      "password",
    );
    await expect(page.locator('label[for="username"]')).toBeVisible();
    await expect(page.locator('label[for="password"]')).toBeVisible();
  });

  test("should handle keyboard navigation", async ({ page }) => {
    // Fill in some values so button becomes enabled for focus
    await page.fill('input[type="text"]', "test");
    await page.fill('input[type="password"]', "test");

    // Click somewhere else first to reset focus, then start tab navigation
    await page.click("h2");
    await page.keyboard.press("Tab");
    await expect(page.locator('input[type="text"]')).toBeFocused();

    await page.keyboard.press("Tab");
    await expect(page.locator('input[type="password"]')).toBeFocused();

    await page.keyboard.press("Tab");
    await expect(page.locator('button[type="submit"]')).toBeFocused();
  });
});

test.describe("Error Handling", () => {
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
    await waitForLoginHydration(page);
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
    await waitForLoginHydration(page);
    await page.fill('input[type="text"]', "admin");
    await page.fill('input[type="password"]', "admin");

    // Wait for the submit button to become enabled after filling the form
    await page.waitForSelector('button[type="submit"]:not([disabled])');
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
    await waitForLoginHydration(page);

    // Login form should be visible and usable
    await expect(page.locator('input[type="text"]')).toBeVisible();
    await expect(page.locator('input[type="password"]')).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toBeVisible();
  });

  test("should work on tablet viewport", async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 }); // iPad

    await page.goto("/login");
    await waitForLoginHydration(page);

    // Interface should adapt to tablet size
    await expect(page.locator(".max-w-md")).toBeVisible();
  });

  test("should work on desktop viewport", async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 }); // Desktop

    await page.goto("/login");
    await waitForLoginHydration(page);

    // Should use full width appropriately
    await expect(page.locator('input[type="text"]')).toBeVisible();
  });
});

test.describe("Performance", () => {
  test("should load login page quickly", async ({ page }) => {
    const startTime = Date.now();
    await page.goto("/login");
    await waitForLoginHydration(page);
    await page.waitForLoadState("networkidle");
    const loadTime = Date.now() - startTime;

    // Should load within 3 seconds
    expect(loadTime).toBeLessThan(3000);
  });

  test("should have no console errors on login page", async ({ page }) => {
    // Mock all API endpoints to prevent 404 errors
    await page.route("http://localhost:8000/**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ok: true }),
      });
    });

    const errors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        errors.push(msg.text());
      }
    });

    await page.goto("/login");
    await waitForLoginHydration(page);
    await page.waitForLoadState("networkidle");

    // Filter out known development warnings
    const realErrors = errors.filter(
      (error) =>
        !error.includes("React DevTools") &&
        !error.includes("Download the React DevTools") &&
        !error.includes("Failed to load resource"),
    );

    expect(realErrors).toHaveLength(0);
  });
});

test.describe("Security", () => {
  test("should not expose sensitive data in HTML", async ({ page }) => {
    await page.goto("/login");
    await waitForLoginHydration(page);

    const content = await page.content();

    // Should not contain any hardcoded credentials or secrets
    expect(content).not.toContain("admin");
    expect(content).not.toContain("password123");
    expect(content).not.toContain("secret");
    expect(content).not.toContain("token");
  });

  test("should have proper form security attributes", async ({ page }) => {
    await page.goto("/login");
    await waitForLoginHydration(page);

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
    await waitForLoginHydration(page);

    // Should have loaded successfully despite any CSP restrictions
    expect(response?.status()).toBe(200);
  });
});

import { Page, expect } from "@playwright/test";

/**
 * Test utilities for common actions and assertions
 */
export class TestUtils {
  constructor(private page: Page) {}

  /**
   * Perform login with given credentials
   */
  async login(username: string = "admin", password: string = "admin") {
    await this.page.goto("/login");
    await this.page.fill('input[type="text"]', username);
    await this.page.fill('input[type="password"]', password);
    await this.page.click('button[type="submit"]');
  }

  /**
   * Mock successful authentication
   */
  async mockAuth() {
    await this.page.addInitScript(() => {
      document.cookie = "rag_session=mock-session-token; Path=/";
    });
  }

  /**
   * Mock API endpoints for testing
   */
  async mockAPI() {
    // Mock all API calls to localhost:8000
    await this.page.route("http://localhost:8000/**", async (route) => {
      const url = route.request().url();

      if (url.includes("/models")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            { id: "gpt-3.5-turbo", label: "GPT-3.5 Turbo" },
            { id: "gpt-4", label: "GPT-4" },
            { id: "claude-3", label: "Claude 3" },
          ]),
        });
      } else if (url.includes("/auth/logout")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ok: true }),
        });
      } else if (url.includes("/auth/login")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ok: true }),
          headers: {
            "Set-Cookie": "rag_session=mock-session-token; Path=/; HttpOnly",
          },
        });
      } else if (url.includes("/search")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            ok: true,
            results: [
              {
                id: "mock-1",
                text: "This is a mocked search result",
                chat_id: "-100123456789",
                message_id: 123,
                chunk_idx: 0,
                score: 0.95,
                sender: "Test User",
                message_date: Math.floor(Date.now() / 1000),
                source_title: "Test Chat",
                chat_type: "supergroup",
              },
            ],
          }),
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
  }

  /**
   * Send a chat message
   */
  async sendMessage(message: string) {
    await this.page.fill("textarea", message);
    await this.page.click('button:has-text("Send")');
  }

  /**
   * Wait for models to load
   */
  async waitForModelsLoaded() {
    await expect(this.page.locator(".bg-green-500")).toBeVisible({
      timeout: 10000,
    });
  }

  /**
   * Select a model from the dropdown
   */
  async selectModel(modelName: string) {
    await this.waitForModelsLoaded();
    await this.page.click("button:has(.bg-green-500)");
    await this.page.click(`text=${modelName}`);
  }

  /**
   * Check if user is authenticated (on app page)
   */
  async assertAuthenticated() {
    await expect(this.page).toHaveURL("/app");
    await expect(this.page.locator("h1").first()).toContainText("RAG Chat");
  }

  /**
   * Check if user is not authenticated (on login page)
   */
  async assertNotAuthenticated() {
    await expect(this.page).toHaveURL("/login");
    await expect(this.page.locator("h2").first()).toContainText(
      "Sign in to RAG Chat",
    );
  }

  /**
   * Mock network error
   */
  async mockNetworkError(url: string) {
    await this.page.route(url, async (route) => {
      await route.abort("failed");
    });
  }

  /**
   * Mock slow response
   */
  async mockSlowResponse(url: string, delayMs: number = 5000) {
    await this.page.route(url, async (route) => {
      await new Promise((resolve) => setTimeout(resolve, delayMs));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ success: true }),
      });
    });
  }

  /**
   * Take screenshot for debugging
   */
  async screenshot(name: string) {
    await this.page.screenshot({
      path: `test-results/${name}-${Date.now()}.png`,
      fullPage: true,
    });
  }

  /**
   * Check console for errors
   */
  async checkConsoleErrors(): Promise<string[]> {
    const errors: string[] = [];
    this.page.on("console", (msg) => {
      if (msg.type() === "error") {
        errors.push(msg.text());
      }
    });

    return errors.filter(
      (error) =>
        !error.includes("React DevTools") &&
        !error.includes("Download the React DevTools"),
    );
  }

  /**
   * Wait for network idle
   */
  async waitForNetworkIdle() {
    await this.page.waitForLoadState("networkidle");
  }

  /**
   * Fill form and submit
   */
  async submitForm(
    formData: Record<string, string>,
    submitButtonText: string = "Submit",
  ) {
    for (const [selector, value] of Object.entries(formData)) {
      await this.page.fill(selector, value);
    }
    await this.page.click(`button:has-text("${submitButtonText}")`);
  }

  /**
   * Check accessibility
   */
  async checkAccessibility() {
    // Check for proper ARIA labels
    const inputs = await this.page.locator("input").all();
    for (const input of inputs) {
      const id = await input.getAttribute("id");
      if (id) {
        await expect(this.page.locator(`label[for="${id}"]`)).toBeVisible();
      }
    }
  }

  /**
   * Test keyboard navigation
   */
  async testKeyboardNavigation(expectedFocusSequence: string[]) {
    // Fill in form fields first to enable submit button if needed
    if (expectedFocusSequence.includes('button[type="submit"]')) {
      await this.page.fill('input[type="text"]', "test");
      await this.page.fill('input[type="password"]', "test");
    }

    // Click somewhere neutral to reset focus, then start tab navigation
    await this.page.click("h2");

    for (const selector of expectedFocusSequence) {
      await this.page.keyboard.press("Tab");
      await expect(this.page.locator(selector)).toBeFocused();
    }
  }
}

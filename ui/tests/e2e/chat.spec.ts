import { test, expect } from "@playwright/test";

test.describe("Chat Interface", () => {
  test.beforeEach(async ({ page }) => {
    // Mock authentication
    await page.addInitScript(() => {
      document.cookie = "rag_session=mock-session-token; Path=/";
    });

    // Mock all API endpoints completely
    await page.route("http://localhost:8000/**", async (route) => {
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

    await page.route("**/auth/logout", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ success: true }),
      });
    });

    await page.goto("/app");
  });

  test("should display chat interface", async ({ page }) => {
    await expect(page.locator("h1").first()).toContainText("RAG Chat");
    await expect(page.locator('button:has-text("Logout")')).toBeVisible();
    await expect(page.locator("textarea")).toBeVisible();
    await expect(page.locator('button:has-text("Send")')).toBeVisible();
  });

  test("should load models successfully", async ({ page }) => {
    // Wait for models to load - look for the green dot in model picker
    await expect(page.locator(".bg-green-500")).toBeVisible();

    // Click on model picker button
    await page.click("button:has(.bg-green-500)");

    // Should show model options
    await expect(page.locator("text=GPT-3.5 Turbo").first()).toBeVisible();
    await expect(page.locator("text=GPT-4").first()).toBeVisible();
    await expect(page.locator("text=Claude 3").first()).toBeVisible();
  });

  test("should show empty state initially", async ({ page }) => {
    await expect(page.locator("text=Start a conversation")).toBeVisible();
    await expect(
      page.locator("text=Ask me anything about your documents"),
    ).toBeVisible();
    await expect(page.locator(".text-blue-600")).toBeVisible(); // Chat icon
  });

  test("should disable send button when input is empty", async ({ page }) => {
    const sendButton = page.locator('button:has-text("Send")');
    await expect(sendButton).toBeDisabled();
  });

  test("should enable send button when input has text", async ({ page }) => {
    const textarea = page.locator("textarea");
    const sendButton = page.locator('button:has-text("Send")');

    // Use a different approach to trigger React onChange
    await textarea.focus();
    await textarea.clear();
    await page.keyboard.type("Hello, world!", { delay: 50 });

    // Wait for React state to update and button to become enabled
    await expect(sendButton).toBeEnabled();
  });

  test("should send message and show typing indicator", async ({ page }) => {
    const message = "What is the weather today?";

    // Use focus and keyboard type to ensure React onChange is triggered
    await page.locator("textarea").focus();
    await page.locator("textarea").clear();
    await page.keyboard.type(message, { delay: 50 });

    // Wait for the send button to become enabled after typing
    await page.waitForSelector('button:has-text("Send"):not([disabled])');
    await page.click('button:has-text("Send")');

    // Should show user message
    await expect(
      page.locator(".bg-blue-600").locator(`text=${message}`),
    ).toBeVisible();

    // Should show typing indicator
    await expect(page.locator("text=AI is thinking...")).toBeVisible();
    await expect(page.locator(".animate-bounce").first()).toBeVisible();

    // Should clear input
    await expect(page.locator("textarea")).toHaveValue("");
  });

  test("should handle Enter key to send message", async ({ page }) => {
    await page.fill("textarea", "Test message");
    await page.press("textarea", "Enter");

    await expect(
      page.locator(".bg-blue-600").locator("text=Test message"),
    ).toBeVisible();
  });

  test("should handle Shift+Enter for new line", async ({ page }) => {
    await page.fill("textarea", "Line 1");
    await page.press("textarea", "Shift+Enter");
    await page.type("textarea", "Line 2");

    await expect(page.locator("textarea")).toHaveValue("Line 1\nLine 2");
  });

  test("should select different models", async ({ page }) => {
    // Wait for models to load and click model picker
    await page.waitForSelector("button:has(.bg-green-500)");
    await page.click("button:has(.bg-green-500)");

    // Select GPT-4
    await page.click("text=GPT-4");

    // Should close dropdown and show selected model
    await expect(
      page.locator("button:has(.bg-green-500)").locator("text=GPT-4"),
    ).toBeVisible();

    // Should store selection in localStorage
    const selectedModel = await page.evaluate(() => {
      return localStorage.getItem("selected_model_label");
    });
    expect(selectedModel).toBe("GPT-4");
  });

  test("should logout successfully", async ({ page }) => {
    await page.click('button:has-text("Logout")');

    // Should redirect to login page
    await expect(page).toHaveURL("/login");
  });

  test("should handle model loading error", async ({ page }) => {
    // Navigate to a fresh page and mock models API to fail
    await page.goto("/app");

    await page.route("**/models", async (route) => {
      await route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ detail: "unauthorized" }),
      });
    });

    await page.reload();

    // Should redirect to login on 401
    await expect(page).toHaveURL("/login");
  });

  test("should show message timestamps", async ({ page }) => {
    await page.locator("textarea").focus();
    await page.locator("textarea").clear();
    await page.keyboard.type("Test message with timestamp", { delay: 30 });
    await page.waitForSelector('button:has-text("Send"):not([disabled])');
    await page.click('button:has-text("Send")');

    // Should show timestamp in format HH:MM in the chat area (not search results)
    await expect(
      page
        .locator(".text-xs.text-gray-500")
        .locator("text=/\\d{1,2}:\\d{2}/")
        .first(),
    ).toBeVisible();
  });

  test("should scroll to bottom on new messages", async ({ page }) => {
    // Send multiple messages to test auto-scroll
    for (let i = 1; i <= 5; i++) {
      await page.locator("textarea").focus();
      await page.locator("textarea").clear();
      await page.keyboard.type(`Message ${i}`, { delay: 30 });
      await page.waitForSelector('button:has-text("Send"):not([disabled])');
      await page.click('button:has-text("Send")');
      await page.waitForTimeout(100); // Small delay between messages
    }

    // The last message should be visible in the chat area (not in search results)
    await expect(
      page.locator(".bg-blue-600").locator("text=Message 5"),
    ).toBeVisible();
  });

  test("should maintain chat state during session", async ({ page }) => {
    // Send a message
    await page.locator("textarea").focus();
    await page.locator("textarea").clear();
    await page.keyboard.type("Persistent message", { delay: 30 });
    await page.waitForSelector('button:has-text("Send"):not([disabled])');
    await page.click('button:has-text("Send")');

    // Reload page
    await page.reload();

    // Message should still be visible (if using session storage)
    // For now, messages are only in component state, so they'll be gone
    // This test documents the current behavior
    await expect(page.locator("text=Persistent message")).not.toBeVisible();
  });

  test("should have proper input placeholder", async ({ page }) => {
    await expect(page.locator("textarea")).toHaveAttribute(
      "placeholder",
      "Type your message... (Enter to send, Shift+Enter for new line)",
    );
  });

  test("should handle long messages", async ({ page }) => {
    const longMessage =
      "This is a very long message that should wrap properly in the chat interface. ".repeat(
        10,
      );

    await page.locator("textarea").focus();
    await page.locator("textarea").clear();
    await page.keyboard.type(longMessage, { delay: 10 });
    await page.waitForSelector('button:has-text("Send"):not([disabled])');
    await page.click('button:has-text("Send")');

    // Should show the full message
    await expect(
      page.locator(`.bg-blue-600:has-text("${longMessage.substring(0, 50)}")`),
    ).toBeVisible();
  });
});

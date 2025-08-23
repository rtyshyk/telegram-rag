import { test, expect } from '@playwright/test';

test.describe('Login Page', () => {
  test.beforeEach(async ({ page }) => {
    // Mock the API endpoints
    await page.route('**/auth/login', async (route) => {
      const request = route.request();
      const body = JSON.parse(request.postData() || '{}');
      
      if (body.username === 'admin' && body.password === 'admin') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true }),
          headers: {
            'Set-Cookie': 'rag_session=mock-session-token; Path=/; HttpOnly',
            'Access-Control-Allow-Credentials': 'true',
            'Access-Control-Allow-Origin': 'http://localhost:4321'
          }
        });
      } else if (body.username === 'rate-limited') {
        await route.fulfill({
          status: 429,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'too_many_attempts' })
        });
      } else {
        await route.fulfill({
          status: 401,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'invalid_credentials' })
        });
      }
    });

    await page.goto('/login');
  });

  test('should display login form', async ({ page }) => {
    await expect(page.locator('h2').first()).toContainText('Sign in to RAG Chat');
    await expect(page.locator('input[type="text"]')).toBeVisible();
    await expect(page.locator('input[type="password"]')).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toContainText('Sign in');
  });

  test('should show validation for empty fields', async ({ page }) => {
    const submitButton = page.locator('button[type="submit"]');
    await expect(submitButton).toBeDisabled();
  });

  test('should enable submit button when fields are filled', async ({ page }) => {
    await page.fill('input[type="text"]', 'admin');
    await page.fill('input[type="password"]', 'admin');
    
    const submitButton = page.locator('button[type="submit"]');
    await expect(submitButton).toBeEnabled();
  });

  test('should login successfully with valid credentials', async ({ page }) => {
    await page.fill('input[type="text"]', 'admin');
    await page.fill('input[type="password"]', 'admin');
    await page.click('button[type="submit"]');

    // Should redirect to app page
    await expect(page).toHaveURL('/app');
  });

  test('should show error for invalid credentials', async ({ page }) => {
    await page.fill('input[type="text"]', 'wrong');
    await page.fill('input[type="password"]', 'wrong');
    await page.click('button[type="submit"]');

    await expect(page.locator('.text-red-700')).toContainText('invalid credentials');
  });

  test('should show rate limit error', async ({ page }) => {
    await page.fill('input[type="text"]', 'rate-limited');
    await page.fill('input[type="password"]', 'password');
    await page.click('button[type="submit"]');

    await expect(page.locator('.text-red-700')).toContainText('too many attempts');
  });

  test('should show loading state during login', async ({ page }) => {
    // Delay the login response to test loading state
    await page.route('**/auth/login', async (route) => {
      await new Promise(resolve => setTimeout(resolve, 1000));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true })
      });
    });

    await page.fill('input[type="text"]', 'admin');
    await page.fill('input[type="password"]', 'admin');
    await page.click('button[type="submit"]');

    // Should show loading state
    await expect(page.locator('button[type="submit"]')).toContainText('Signing in...');
    await expect(page.locator('.animate-spin')).toBeVisible();
  });

  test('should have proper accessibility attributes', async ({ page }) => {
    await expect(page.locator('input[type="text"]')).toHaveAttribute('id', 'username');
    await expect(page.locator('input[type="password"]')).toHaveAttribute('id', 'password');
    await expect(page.locator('label[for="username"]')).toBeVisible();
    await expect(page.locator('label[for="password"]')).toBeVisible();
  });

  test('should handle keyboard navigation', async ({ page }) => {
    // Fill in some values so button becomes enabled for focus
    await page.fill('input[type="text"]', 'test');
    await page.fill('input[type="password"]', 'test');
    
    // Click somewhere else first to reset focus, then start tab navigation
    await page.click('h2');
    await page.keyboard.press('Tab');
    await expect(page.locator('input[type="text"]')).toBeFocused();
    
    await page.keyboard.press('Tab');
    await expect(page.locator('input[type="password"]')).toBeFocused();
    
    await page.keyboard.press('Tab');
    await expect(page.locator('button[type="submit"]')).toBeFocused();
  });
});

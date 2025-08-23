# Testing Guide

This project includes comprehensive testing with unit tests, integration tests, and end-to-end (E2E) tests using Playwright.

## Test Structure

```
ui/tests/
├── login.spec.ts          # Login functionality tests
├── chat.spec.ts           # Chat interface tests  
├── integration.spec.ts    # Navigation, error handling, performance
├── workflows.spec.ts      # Complete user workflow tests
└── utils/
    └── test-utils.ts      # Shared test utilities
```

## Running Tests

### E2E Tests (Playwright)

```bash
# Run all E2E tests
cd ui && npm run test:e2e

# Run tests with UI (interactive mode)
npm run test:e2e:ui

# Run tests in headed mode (see browser)
npm run test:e2e:headed

# Debug tests
npm run test:e2e:debug
```

### Unit Tests

```bash
# Run UI unit tests
cd ui && npm test

# Run API unit tests (setup required)
cd api
pip install -r requirements.txt  # Install app dependencies
pip install pytest httpx         # Install test dependencies
python -m pytest tests/ -v       # Run tests with verbose output
```

## Test Features

### 🎭 Playwright E2E Tests

- **API Mocking**: All external API calls are mocked for consistent testing
- **Real API Integration**: Separate tests that work with actual backend
- **Cross-browser**: Tests run on Chromium, Firefox, and WebKit
- **Mobile/Responsive**: Tests include mobile and tablet viewport testing
- **Accessibility**: Tests check for proper ARIA labels and keyboard navigation
- **Performance**: Load time and console error checking
- **Security**: Tests for proper form security and data exposure

### 🧪 Test Categories

1. **Login Tests** (`login.spec.ts`)
   - Form validation
   - Authentication flow
   - Error handling (401, 429, timeouts)
   - Loading states
   - Accessibility

2. **Chat Interface** (`chat.spec.ts`)
   - Message sending and display
   - Model selection
   - Typing indicators
   - Auto-scroll behavior
   - Keyboard shortcuts

3. **Integration Tests** (`integration.spec.ts`)
   - Routing and navigation
   - Error handling
   - Responsive design
   - Performance checks
   - Security validations

4. **Workflow Tests** (`workflows.spec.ts`)
   - Complete user journeys
   - Error recovery flows
   - Session management

### 🔧 Test Utilities

The `TestUtils` class provides reusable methods:

```typescript
const utils = new TestUtils(page);

// Authentication
await utils.login('admin', 'password');
await utils.mockAuth();

// API mocking
await utils.mockAPI();
await utils.mockNetworkError('**/auth/login');
await utils.mockSlowResponse('**/models', 5000);

// Chat actions
await utils.sendMessage('Hello');
await utils.selectModel('GPT-4');

// Assertions
await utils.assertAuthenticated();
await utils.assertNotAuthenticated();

// Utilities
await utils.screenshot('debug-image');
await utils.checkAccessibility();
```

## CI/CD Integration

### GitHub Actions

Tests run automatically on:
- Push to `main` or `develop` branches
- Pull requests

### CI Pipeline

1. **Lint & Format** - Pre-commit hooks
2. **Unit Tests** - Jest/Vitest for UI, pytest for API
3. **Build** - Verify all components build successfully
4. **E2E Tests** - Playwright tests with mocked APIs
5. **Integration** - Docker Compose smoke tests

### Test Reports

- Playwright generates HTML reports with screenshots
- Test artifacts are saved for 30 days
- Failed tests include screenshots and traces

## Mock API Endpoints

E2E tests use mocked endpoints for consistency:

```typescript
// Login endpoint
POST /auth/login
- admin/admin → 200 (success)
- rate-limited/* → 429 (rate limit)
- anything else → 401 (invalid)

// Models endpoint  
GET /models
- Returns: [{ id: 'gpt-3.5-turbo', label: 'GPT-3.5 Turbo' }, ...]

// Logout endpoint
POST /auth/logout
- Always returns 200
```

## Writing New Tests

### Basic Test Structure

```typescript
import { test, expect } from '@playwright/test';
import { TestUtils } from './utils/test-utils';

test.describe('Feature Name', () => {
  let utils: TestUtils;

  test.beforeEach(async ({ page }) => {
    utils = new TestUtils(page);
    await utils.mockAPI(); // Mock APIs if needed
  });

  test('should do something', async ({ page }) => {
    // Test implementation
  });
});
```

### Best Practices

1. **Use Page Object Model**: Utilize `TestUtils` for common actions
2. **Mock External Dependencies**: Use `utils.mockAPI()` for consistent tests
3. **Test User Journeys**: Focus on complete workflows, not just individual features
4. **Include Error Cases**: Test network failures, timeouts, and edge cases
5. **Check Accessibility**: Use `utils.checkAccessibility()` where appropriate
6. **Mobile Testing**: Include responsive design tests
7. **Performance**: Check load times and console errors

### Example Test

```typescript
test('complete login and chat workflow', async ({ page }) => {
  // Setup
  await utils.mockAPI();
  
  // Login
  await utils.login();
  await utils.assertAuthenticated();
  
  // Use chat
  await utils.waitForModelsLoaded();
  await utils.selectModel('GPT-4');
  await utils.sendMessage('Hello!');
  
  // Verify
  await expect(page.locator('.bg-blue-600').locator('text=Hello!')).toBeVisible();
  
  // Cleanup
  await page.click('button:has-text("Logout")');
  await utils.assertNotAuthenticated();
});
```

## Debugging Tests

### Local Debugging

```bash
# Run in headed mode to see browser
npm run test:e2e:headed

# Run with debugger
npm run test:e2e:debug

# Run specific test file
npx playwright test login.spec.ts

# Run specific test
npx playwright test -g "should login successfully"
```

### CI Debugging

- Check uploaded Playwright reports in GitHub Actions artifacts
- Review screenshots and traces for failed tests
- Check console logs in test output

## Configuration

Key configuration files:
- `playwright.config.ts` - Main Playwright configuration
- `.github/workflows/ci.yml` - CI pipeline
- `.github/workflows/e2e-tests.yml` - Dedicated E2E testing workflow

The tests are designed to be reliable, fast, and comprehensive, providing confidence in deployments and protecting against regressions.

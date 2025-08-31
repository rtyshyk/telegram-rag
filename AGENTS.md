# GitHub Copilot Instructions

Repository: https://github.com/rtyshyk/telegram-rag

## Code Quality Requirements

**MANDATORY: After implementing ANY feature, bug fix, or code change, you MUST run formatting and linting tools:**

```bash
# Always run before committing
pre-commit run --all-files
```

## Required Development Workflow

1. **Implement feature/fix**
2. **Format & lint code** (MANDATORY):
   ```bash
   pre-commit run --all-files
   ```
3. **Verify all hooks pass** - no exceptions
4. **Run relevant tests** (MANDATORY) - use VS Code tools, not terminal commands
5. **Commit with proper formatting**

## Testing Requirements

### Always Use VS Code Testing Tools

**MANDATORY: Use VS Code built-in testing tools instead of terminal commands:**

- **For Python tests**: Use `runTests` tool with specific file paths
- **For JavaScript/TypeScript tests**: Use VS Code test runner integration
- **Never use terminal commands** like `pytest`, `npm test`, `vitest` directly
- **Always verify tests pass** before committing changes
- **Never write stubs in the production code**

### VS Code Test Explorer Integration

**CRITICAL: Prevent Test Discovery Failures**

When creating or modifying tests that need VS Code test explorer integration:

1. **Configure Python Environment**: Always call `configure_python_environment` before running tests
2. **Avoid Global Module Mocking**: Never use `sys.modules["module_name"] = MagicMock()` at module level
3. **Use Proper Test Isolation**: Mock dependencies within test functions or fixtures, not globally

**Known Issue - Global Module Mocking:**

- **Problem**: Global mocking (e.g., `sys.modules["settings"] = MagicMock()`) affects ALL tests when pytest runs the entire suite
- **Symptom**: Tests pass individually but fail when run together, showing "TypeError: '>' not supported between instances of 'MagicMock' and 'int'"
- **Root Cause**: Global mocks from one test file affect imports in other test files
- **Solution**: Use proper test fixtures and context managers for mocking instead of global module replacement

**Test Fixture Best Practices:**

- Create real objects for direct testing (e.g., `CLIArgs` instances)
- Use `patch()` context managers or `@patch` decorators for dependencies
- Mock at the function/method level, not module level
- Include all required attributes when creating mock objects

## Code Standards

### Python

- Use `black` for formatting (auto-applied by pre-commit)
- Include type hints for all functions
- Follow async/await patterns for I/O operations
- Use `pytest` for testing

### Shell Scripts

- Use `shfmt` formatting (auto-applied by pre-commit)
- Start with `set -euo pipefail`
- Use proper error handling and quotes

### Markdown/Documentation

- Use `prettier` formatting (auto-applied by pre-commit)
- Include code block language identifiers
- Keep documentation up-to-date with changes

## Architecture Patterns

### Docker Services

- Always include health checks
- Use proper dependency management with `depends_on`
- Implement graceful startup/shutdown
- Use read-only volumes when possible

### Vespa Integration

- Application packages auto-deploy on startup
- Health checks verify both Vespa and application status
- Use proper session-based deployment API

### Error Handling

- Implement comprehensive error handling
- Use structured logging
- Set appropriate timeouts
- Provide clear error messages

## Never Skip

- Pre-commit hook execution
- Code formatting
- **Running tests with VS Code tools** (not terminal commands)
- **Python environment configuration** for test discovery
- **Test isolation** (avoid global mocking that affects other tests)
- Documentation updates for new features
- Health check implementations
- Proper error handling

Remember: **Quality code is formatted code. Always run pre-commit hooks after any changes!**
Remember: **Reliable code is tested code. Always use VS Code testing tools to verify functionality!**
Remember: **Isolated tests are reliable tests. Avoid global mocking that affects test discovery!**

## Supported models

The models exists and naming is correct. label -> value. do do not rename it.

- "gpt 5": "gpt-5",
- "gpt5 mini": "gpt-5-mini",
- "gpt5 nano": "gpt-5-nano",

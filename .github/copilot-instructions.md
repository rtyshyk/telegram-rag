# GitHub Copilot Instructions

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
4. **Run relevant tests** if applicable
5. **Commit with proper formatting**

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
- Documentation updates for new features
- Health check implementations
- Proper error handling

Remember: **Quality code is formatted code. Always run pre-commit hooks after any changes!**

#!/bin/bash
set -euo pipefail

# GitHub MCP Setup Script
# This script helps set up GitHub MCP integration for the telegram-rag project

echo "🚀 Setting up GitHub MCP Integration"
echo "===================================="

# Check if mcp-config.json exists
if [[ ! -f "mcp-config.json" ]]; then
    echo "❌ mcp-config.json not found!"
    echo "Please run this script from the project root directory."
    exit 1
fi

# Check if .env file exists
if [[ ! -f ".env" ]]; then
    echo "📋 Creating .env file from .env.example..."
    cp .env.example .env
    echo "✅ .env file created"
else
    echo "✅ .env file already exists"
fi

# Check if GitHub token is configured
if grep -q "GITHUB_PERSONAL_ACCESS_TOKEN=ghp_your_personal_access_token_here" .env 2>/dev/null; then
    echo ""
    echo "⚠️  GitHub Personal Access Token needs to be configured!"
    echo ""
    echo "To set up your GitHub token:"
    echo "1. Go to: https://github.com/settings/tokens"
    echo "2. Click 'Generate new token (classic)'"
    echo "3. Select these scopes:"
    echo "   - repo (Full control of private repositories)"
    echo "   - read:org (Read org and team membership)"
    echo "   - read:user (Read user profile data)"
    echo "   - workflow (Update GitHub Action workflows)"
    echo "4. Copy the generated token"
    echo "5. Edit .env and replace 'ghp_your_personal_access_token_here' with your token"
    echo ""
elif grep -q "GITHUB_PERSONAL_ACCESS_TOKEN=ghp_" .env 2>/dev/null; then
    echo "✅ GitHub Personal Access Token appears to be configured"
else
    echo "⚠️  Please add GITHUB_PERSONAL_ACCESS_TOKEN to your .env file"
fi

# Check if Node.js is available (needed for the MCP server)
if command -v node >/dev/null 2>&1; then
    echo "✅ Node.js is available ($(node --version))"
else
    echo "❌ Node.js is required for GitHub MCP server"
    echo "Please install Node.js: https://nodejs.org/"
    exit 1
fi

# Check if npx is available
if command -v npx >/dev/null 2>&1; then
    echo "✅ npx is available"
else
    echo "❌ npx is required for GitHub MCP server"
    echo "Please install Node.js with npm: https://nodejs.org/"
    exit 1
fi

echo ""
echo "🎉 GitHub MCP setup complete!"
echo ""
echo "Next steps:"
echo "1. Configure your GitHub Personal Access Token in .env if not done already"
echo "2. The MCP configuration is ready in mcp-config.json"
echo "3. AI assistants can now use the GitHub MCP integration"
echo ""
echo "For more information, see the 'GitHub MCP Integration' section in README.md"

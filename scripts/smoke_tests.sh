#!/usr/bin/env bash
set -euo pipefail

echo "🚀 Starting smoke tests..."

# Test API health
echo -n "📡 Testing API health... "
if curl -fsS http://localhost:8000/healthz | grep -q '"status":"ok"'; then
	echo "✅ PASS"
else
	echo "❌ FAIL"
	exit 1
fi

# Test UI login page (try both development and production ports)
echo -n "🌐 Testing UI availability... "
if curl -fsS http://localhost:4321/login >/dev/null 2>&1; then
	echo "✅ PASS (development port 4321)"
	UI_PORT=4321
elif curl -fsS http://localhost:3000/login >/dev/null 2>&1; then
	echo "✅ PASS (production port 3000)"
	UI_PORT=3000
else
	echo "❌ FAIL (not available on ports 3000 or 4321)"
	exit 1
fi

# Test Vespa
echo -n "🔍 Testing Vespa search engine... "
if curl -fsS http://localhost:19071/ApplicationStatus >/dev/null; then
	echo "✅ PASS"
else
	echo "❌ FAIL"
	exit 1
fi

# Test authentication
echo -n "🔐 Testing authentication... "
if curl -fsS -c cookies.txt -H 'Content-Type: application/json' \
	-d '{"username":"admin","password":"password"}' \
	http://localhost:8000/auth/login | grep -q '"ok":true'; then
	echo "✅ PASS"
else
	echo "❌ FAIL"
	exit 1
fi

# Test models endpoint
echo -n "🤖 Testing models endpoint... "
if curl -fsS -b cookies.txt http://localhost:8000/models | grep -q 'gpt-5'; then
	echo "✅ PASS"
else
	echo "❌ FAIL"
	exit 1
fi

echo ""
echo "🎉 All smoke tests passed successfully!"

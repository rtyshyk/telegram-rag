#!/usr/bin/env bash
set -euo pipefail

# Test API health
curl -fsS http://localhost:8000/healthz | grep -q '"status":"ok"'

# Test UI login page (try both development and production ports)
if curl -fsS http://localhost:4321/login >/dev/null 2>&1; then
	echo "✅ UI available on development port (4321)"
	UI_PORT=4321
elif curl -fsS http://localhost:3000/login >/dev/null 2>&1; then
	echo "✅ UI available on production port (3000)"
	UI_PORT=3000
else
	echo "❌ UI not available on either port 3000 or 4321"
	exit 1
fi

# Test Vespa
curl -fsS http://localhost:19071/ApplicationStatus >/dev/null

# Test authentication
curl -fsS -c cookies.txt -H 'Content-Type: application/json' \
	-d '{"username":"admin","password":"password"}' \
	http://localhost:8000/auth/login | grep -q '"ok":true'

# Test models endpoint
curl -fsS -b cookies.txt http://localhost:8000/models | grep -q 'gpt-5'

echo "✅ All smoke tests passed"

#!/usr/bin/env bash
set -euo pipefail

curl -fsS http://localhost:8000/healthz | grep -q '"status":"ok"'
curl -fsS http://localhost:3000/login | grep -q 'Login'
curl -fsS http://localhost:19071/ApplicationStatus >/dev/null

curl -fsS -c cookies.txt -H 'Content-Type: application/json' \
	-d '{"username":"'"${APP_USER}"'","password":"password"}' \
	http://localhost:8000/auth/login | grep -q '"ok": true'
curl -fsS -b cookies.txt http://localhost:8000/models | grep -q 'gpt-5'

echo "Smoke tests passed"

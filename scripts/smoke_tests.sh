#!/usr/bin/env bash
set -euo pipefail

curl -fsS http://localhost:8000/healthz | grep -q '"status":"ok"'
curl -fsS http://localhost:3000/ | grep -q 'Stack is up'
curl -fsS http://localhost:19071/ApplicationStatus >/dev/null

echo "Smoke tests passed"

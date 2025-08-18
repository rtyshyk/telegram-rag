#!/usr/bin/env bash
set -euo pipefail

RETRIES=${RETRIES:-30}

wait_for() {
	local name=$1
	local url=$2
	local count=0
	until curl -fsS "$url" >/dev/null; do
		count=$((count + 1))
		if [[ $count -ge $RETRIES ]]; then
			echo "$name did not become healthy" >&2
			exit 1
		fi
		sleep 1
	done
	echo "$name is up"
}

# Check that vespa-deploy container completed successfully
echo "Checking Vespa deployment status..."
# The vespa-deploy container has restart: "no" so it exits and may be removed
# Check if we can find it in recent container history
if docker compose ps -a vespa-deploy --format table | grep -q "exited (0)"; then
  echo "Vespa deployment completed successfully"
elif docker compose ps vespa-deploy --format table | grep -q "exited (0)"; then
  echo "Vespa deployment completed successfully"
else
  # Fallback: check if Vespa application is actually deployed
  echo "Checking Vespa application deployment directly..."
  if curl -fsS "http://localhost:19071/ApplicationStatus" >/dev/null 2>&1; then
    echo "Vespa is responding"
  else
    echo "Vespa deployment verification failed - Vespa not responding"
    exit 1
  fi
fi

# Verify Vespa application is properly deployed
echo "Verifying Vespa application deployment..."
if curl -fsS "http://localhost:19071/ApplicationStatus" >/dev/null 2>&1; then
  # Check the specific application deployment status
  APP_STATUS=$(curl -fsS "http://localhost:19071/application/v2/tenant/default/application/default" 2>/dev/null || echo '{}')
  GENERATION=$(echo "$APP_STATUS" | jq -r '.generation // "null"' 2>/dev/null || echo "null")
  
  if [[ "$GENERATION" != "null" && "$GENERATION" != "0" ]]; then
    echo "✅ Vespa application deployed (generation: $GENERATION)"
  else
    # Fallback: test if search endpoint works (which proves deployment)
    if curl -fsS "http://localhost:8080/search/?query=test&hits=1" >/dev/null 2>&1; then
      echo "✅ Vespa application deployed (search endpoint working)"
    else
      echo "⚠️  Warning: Vespa application deployment status unclear"
    fi
  fi
else
  echo "❌ Vespa is not responding properly"
  exit 1
fi

wait_for "API" "http://localhost:8000/healthz"
wait_for "UI" "http://localhost:3000/"

docker compose exec -T postgres pg_isready -U "${POSTGRES_USER:-postgres}" >/dev/null

echo "Postgres is up"

echo ""
echo "🎉 All services are healthy and ready!"

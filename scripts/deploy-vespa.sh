#!/bin/bash

# Deploy Vespa application automatically
# This script waits for Vespa to be ready and then deploys the application

set -euo pipefail

VESPA_HOST=${1:-localhost}
VESPA_CONFIG_PORT=${2:-19071}
APPLICATION_DIR=${3:-./vespa/application}

echo "🚀 Starting Vespa application deployment..."
echo "   Vespa host: $VESPA_HOST"
echo "   Config port: $VESPA_CONFIG_PORT"
echo "   Application dir: $APPLICATION_DIR"

# Wait for Vespa config server to be ready
echo "⏳ Waiting for Vespa config server to be ready..."
timeout=300 # 5 minutes
elapsed=0
interval=5

while ! curl -sf "http://$VESPA_HOST:$VESPA_CONFIG_PORT/ApplicationStatus" >/dev/null 2>&1; do
	if [ $elapsed -ge $timeout ]; then
		echo "❌ Timeout waiting for Vespa config server after ${timeout}s"
		exit 1
	fi
	echo "   Vespa not ready yet, waiting ${interval}s... (${elapsed}s elapsed)"
	sleep $interval
	elapsed=$((elapsed + interval))
done

echo "✅ Vespa config server is ready!"

# Deploy the application
echo "📦 Deploying Vespa application..."

# Create zip file of application with correct structure
TEMP_DIR=$(mktemp -d)
ZIP_FILE="$TEMP_DIR/application.zip"

# Change to application directory and zip contents (not the directory itself)
(cd "$APPLICATION_DIR" && zip -r "$ZIP_FILE" .)

echo "   Created application package: $ZIP_FILE"

# Step 1: Create session
echo "   Creating session..."
set +e # Don't exit on error for curl so we can handle it
SESSION_RESPONSE=$(curl -s -X POST -H "Content-Type: application/zip" \
	--data-binary @"$ZIP_FILE" \
	"http://$VESPA_HOST:$VESPA_CONFIG_PORT/application/v2/tenant/default/session")
CURL_EXIT_CODE=$?
set -e # Re-enable exit on error

if [ $CURL_EXIT_CODE -ne 0 ]; then
	echo "❌ Failed to create session (curl exit code: $CURL_EXIT_CODE)"
	rm -rf "$TEMP_DIR"
	exit 1
fi

echo "   Session response: $SESSION_RESPONSE"

# Check if the response contains an error
if echo "$SESSION_RESPONSE" | grep -q '"error-code"'; then
	echo "❌ Session creation failed with error:"
	echo "   $SESSION_RESPONSE"
	rm -rf "$TEMP_DIR"
	exit 1
fi

# Extract session ID
SESSION_ID=$(echo "$SESSION_RESPONSE" | jq -r '.["session-id"] // empty')
if [ -z "$SESSION_ID" ]; then
	echo "❌ Failed to get session ID from response"
	echo "   Full response: $SESSION_RESPONSE"
	rm -rf "$TEMP_DIR"
	exit 1
fi

echo "   Session ID: $SESSION_ID"

# Step 2: Prepare session
echo "   Preparing session..."
PREPARE_RESPONSE=$(curl -s -X PUT \
	"http://$VESPA_HOST:$VESPA_CONFIG_PORT/application/v2/tenant/default/session/$SESSION_ID/prepared")

echo "   Prepare response: $PREPARE_RESPONSE"

# Check if prepare failed
if echo "$PREPARE_RESPONSE" | grep -q '"error-code"'; then
	echo "❌ Session preparation failed with error:"
	echo "   $PREPARE_RESPONSE"
	rm -rf "$TEMP_DIR"
	exit 1
fi

# Step 3: Activate session
echo "   Activating session..."
ACTIVATE_RESPONSE=$(curl -s -X PUT \
	"http://$VESPA_HOST:$VESPA_CONFIG_PORT/application/v2/tenant/default/session/$SESSION_ID/active")

echo "   Activate response: $ACTIVATE_RESPONSE"

# Check if activate failed
if echo "$ACTIVATE_RESPONSE" | grep -q '"error-code"'; then
	echo "❌ Session activation failed with error:"
	echo "   $ACTIVATE_RESPONSE"
	rm -rf "$TEMP_DIR"
	exit 1
fi

# Check if deployment was successful
GENERATION=$(echo "$ACTIVATE_RESPONSE" | jq -r '.application.generation // empty')
if [ -z "$GENERATION" ]; then
	echo "❌ Failed to get generation from activation response"
	echo "   Full response: $ACTIVATE_RESPONSE"
	rm -rf "$TEMP_DIR"
	exit 1
fi

echo "✅ Application deployed successfully!"
echo "   Session ID: $SESSION_ID"
echo "   Generation: $GENERATION"

# Verify deployment by checking application status
echo "🔍 Verifying deployment..."
STATUS_RESPONSE=$(curl -sf "http://$VESPA_HOST:$VESPA_CONFIG_PORT/ApplicationStatus")
GENERATION=$(echo "$STATUS_RESPONSE" | jq -r '.application.meta.generation // empty')

if [ -n "$GENERATION" ] && [ "$GENERATION" != "null" ]; then
	echo "✅ Deployment verified! Application generation: $GENERATION"
else
	echo "⚠️  Could not verify deployment generation"
fi

# Clean up
rm -rf "$TEMP_DIR"

echo "🎉 Vespa application deployment completed successfully!"

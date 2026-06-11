#!/bin/bash
# =============================================================================
# MinIO Bucket Initialization — Agent Crawler
# =============================================================================
# This script runs as a one-shot init container to create required buckets.
# It waits for MinIO to be ready, then creates buckets if they don't exist.

set -e

MINIO_HOST="${MINIO_ENDPOINT:-minio:9000}"
MINIO_ACCESS="${MINIO_ACCESS_KEY:-minioadmin}"
MINIO_SECRET="${MINIO_SECRET_KEY:-minioadmin}"

BUCKETS=(
  "crawler-raw"
  "crawler-clean"
  "crawler-audit"
  "crawler-generated"
)

echo "⏳ Waiting for MinIO at ${MINIO_HOST}..."

# Wait for MinIO to be ready (max 60 seconds)
for i in $(seq 1 30); do
  if mc alias set local "http://${MINIO_HOST}" "${MINIO_ACCESS}" "${MINIO_SECRET}" > /dev/null 2>&1; then
    echo "✅ MinIO is ready"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "❌ MinIO did not become ready in time"
    exit 1
  fi
  sleep 2
done

# Create buckets
for bucket in "${BUCKETS[@]}"; do
  if mc ls "local/${bucket}" > /dev/null 2>&1; then
    echo "  ✓ Bucket '${bucket}' already exists"
  else
    mc mb "local/${bucket}"
    echo "  ✓ Created bucket '${bucket}'"
  fi
done

echo ""
echo "🪣 All buckets ready:"
mc ls local
echo ""
echo "✅ MinIO initialization complete"

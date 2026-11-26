#!/usr/bin/env bash
# Build the Angular app and publish it to the S3 bucket behind CloudFront.
# Requires the stacks to be deployed first: (cd infra && cdk deploy --all --profile <profile>)
#
# Usage:
#   ./deploy-frontend.sh <profile> [region]     (region defaults to eu-west-3)
set -euo pipefail

PROFILE="${1:?Usage: deploy-frontend.sh <profile> [region]}"
REGION="${2:-eu-west-3}"
FRONTEND="$(cd "$(dirname "$0")/../frontend" && pwd)"
OUT="$FRONTEND/dist/nightmare-resolver/browser"

aws_() { aws "$@" --profile "$PROFILE" --region "$REGION"; }
output() {
  aws_ cloudformation describe-stacks --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text
}

echo "Reading stack outputs..."
BUCKET=$(output NightmareResolverWeb BucketName)
DIST=$(output NightmareResolverWeb DistributionId)
SITE=$(output NightmareResolverWeb SiteUrl)
API=$(output NightmareResolver ApiUrl)
echo "  bucket: $BUCKET"
echo "  api:    $API"

echo "Building the app..."
( cd "$FRONTEND" && { [ -d node_modules ] || npm ci; } && npm run build )

# Runtime config: the same build works for any account.
printf '{"apiUrl":"%s"}\n' "$API" > "$OUT/config.json"

echo "Uploading..."
# Hashed assets first (long cache), then index.html and config.json (always revalidated).
aws_ s3 sync "$OUT" "s3://$BUCKET" --delete --exclude index.html --exclude config.json \
  --cache-control "public,max-age=31536000,immutable"
aws_ s3 cp "$OUT/config.json" "s3://$BUCKET/config.json" \
  --cache-control "no-cache" --content-type "application/json"
aws_ s3 cp "$OUT/index.html" "s3://$BUCKET/index.html" \
  --cache-control "no-cache" --content-type "text/html; charset=utf-8"

echo "Invalidating CloudFront cache..."
aws_ cloudfront create-invalidation --distribution-id "$DIST" \
  --paths "/index.html" "/config.json" --query "Invalidation.Id" --output text

echo
echo "Done: $SITE"
echo "Debug panel: $SITE/?debug"

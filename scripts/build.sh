#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[[ ${AUTH_PROVIDER:-authelia} == authelia ]] || { echo 'Provider adapter not implemented' >&2; exit 1; }
SOURCE="$(python3 "$ROOT/scripts/prepare-authelia.py")"
cd "$SOURCE"
go test -race -p 1 ./internal/emailotp
go test -p 1 ./internal/handlers
(cd web && pnpm install --frozen-lockfile --ignore-scripts && pnpm build)
cp -r api internal/server/public_html/
archive="$(mktemp)"
trap 'rm -f -- "$archive"' EXIT
curl -fsSL https://github.com/swagger-api/swagger-ui/archive/v5.33.0.tar.gz -o "$archive"
tar -C internal/server/public_html/api --exclude=index.html --exclude='*.map' \
  --exclude='*-es-*' --exclude=swagger-ui.js --exclude=swagger-initializer.js \
  --strip-components=2 -xf "$archive" swagger-ui-5.33.0/dist
mkdir -p "$ROOT/artifacts"
go build -trimpath -o "$ROOT/artifacts/authelia" ./cmd/authelia
echo 'Authentication binary built; private configuration is supplied separately.'

#!/usr/bin/env bash
# Creates the gateway bearer token in the secrets directory (never in the repo).
#   ./scripts/new-key.sh
set -euo pipefail
dir="${GATEWAY_KEY_FILE:+$(dirname "$GATEWAY_KEY_FILE")}"
dir="${dir:-$HOME/.config/inference-secrets}"
mkdir -p "$dir"
umask 077
key=$(openssl rand -base64 32 | tr -d '=' | tr '/+' '_-')
printf '%s' "$key" > "$dir/gateway.key"
chmod 600 "$dir/gateway.key"
echo "wrote $dir/gateway.key (mode 600)"

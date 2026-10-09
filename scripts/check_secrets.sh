#!/usr/bin/env bash
# Pre-commit secret guard. Install: ln -sf ../../scripts/check_secrets.sh .git/hooks/pre-commit
# 1) never commit .env  2) never commit any value present in .env
# 3) block unmarked 64-char alphanumeric tokens (mark public examples with "allowlist-secret")
set -euo pipefail
if git diff --cached --name-only | grep -qE '(^|/)\.env$'; then
  echo "BLOCKED: .env must never be committed"; exit 1
fi
added=$(git diff --cached -U0 | grep -E '^\+' || true)
if [ -f .env ]; then
  while IFS='=' read -r k v; do
    [[ -z "${v:-}" || "$k" =~ ^# || ${#v} -lt 16 ]] && continue
    if grep -qF -- "$v" <<<"$added"; then echo "BLOCKED: value of $k from .env is staged"; exit 1; fi
  done < .env
fi
if grep -vE 'allowlist-secret' <<<"$added" | grep -qE '[A-Za-z0-9]{64}'; then
  echo "BLOCKED: staged changes contain an unmarked 64-char token (possible API key/secret)"; exit 1
fi

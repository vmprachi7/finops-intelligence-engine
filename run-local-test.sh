#!/bin/bash
# ═══════════════════════════════════════════════════════════
# RUN AUDITOR LOCALLY
# Tests both orphaned detection + right-sizing (mock metrics)
# Run from repo root: bash run-local-test.sh
# ═══════════════════════════════════════════════════════════
set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Running FinOps Resource Auditor locally"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── Check env vars ────────────────────────────────────────────
MISSING=()
[[ -z "$ARM_CLIENT_ID" ]]       && MISSING+=("ARM_CLIENT_ID")
[[ -z "$ARM_CLIENT_SECRET" ]]   && MISSING+=("ARM_CLIENT_SECRET")
[[ -z "$ARM_TENANT_ID" ]]       && MISSING+=("ARM_TENANT_ID")
[[ -z "$ARM_SUBSCRIPTION_ID" ]] && MISSING+=("ARM_SUBSCRIPTION_ID")
[[ -z "$GROQ_API_KEY" ]]        && MISSING+=("GROQ_API_KEY")

if [ ${#MISSING[@]} -gt 0 ]; then
  echo "❌ Missing environment variables:"
  for v in "${MISSING[@]}"; do echo "   $v"; done
  echo ""
  echo "These are in your ~/.zshrc from platform setup."
  echo "Run: source ~/.zshrc"
  exit 1
fi

echo "✅ All environment variables present"
echo ""

# ── Set Azure vars for Python ─────────────────────────────────
export AZURE_SUBSCRIPTION_ID="$ARM_SUBSCRIPTION_ID"
export AZURE_TENANT_ID="$ARM_TENANT_ID"
export AZURE_CLIENT_ID="$ARM_CLIENT_ID"
export AZURE_CLIENT_SECRET="$ARM_CLIENT_SECRET"

# ── Enable mock metrics ───────────────────────────────────────
# Right-sizing needs 7 days of Azure Monitor data.
# MOCK_METRICS=true simulates 8% avg CPU so right-sizing works instantly.
# In production (GitHub Actions), MOCK_METRICS is not set → uses real data.
export MOCK_METRICS="true"

echo "Note: MOCK_METRICS=true — right-sizing uses simulated 8% CPU"
echo "      (avoids 7-day wait for Azure Monitor data)"
echo ""

# ── Run auditor ───────────────────────────────────────────────
echo "🔍 Running auditor..."
echo ""
PYTHONPATH=. python app/resource_auditor.py

# ── Print report preview ──────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Report preview (first 4000 chars):"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

python3 -c "
import json
with open('audit_report.json') as f:
    d = json.load(f)
print('TITLE:', d['title'])
print('')
body = d['body']
print(body[:4000])
if len(body) > 4000:
    print('... [truncated — full report in audit_report.json]')
"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Full report: audit_report.json"
echo ""
echo "  To create a real GitHub Issue:"
echo "  Actions → Resource Audit → Run workflow → dry_run: false"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
#!/bin/bash
# ═══════════════════════════════════════════════════════════
# CLEANUP ALL TEST RESOURCES
# Deletes finops-audit-test-rg and audit-test-empty-rg
# Run after testing is complete
# ═══════════════════════════════════════════════════════════
set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Cleaning up all test resources"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Delete main resource group (VMs, disks, IPs, VNet)
echo "Deleting finops-audit-test-rg..."
az group delete \
  --name "finops-audit-test-rg" \
  --yes --no-wait 2>/dev/null && \
  echo "✅ Deletion started for finops-audit-test-rg" || \
  echo "ℹ️  finops-audit-test-rg not found — already deleted"

# Delete empty resource group
echo "Deleting audit-test-empty-rg..."
az group delete \
  --name "audit-test-empty-rg" \
  --yes --no-wait 2>/dev/null && \
  echo "✅ Deletion started for audit-test-empty-rg" || \
  echo "ℹ️  audit-test-empty-rg not found — already deleted"

# Clean up local files
rm -f audit_report.json issue_body.md
echo "✅ Local audit files removed"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ Cleanup complete (running in background)"
echo "  Verify in Azure Portal after ~2 minutes"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
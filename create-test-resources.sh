#!/bin/bash
# ═══════════════════════════════════════════════════════════
# CREATE ALL TEST RESOURCES
# Uses Standard_D2as_v7 (confirmed available in eastus2)
# Run: bash create-test-resources.sh
# ═══════════════════════════════════════════════════════════
set -e

RG="finops-audit-test-rg"
EMPTY_RG="audit-test-empty-rg"
LOCATION="eastus2"
VM_SIZE="Standard_D2as_v7"   # 2 vCPUs, 8GB — confirmed available
PREFIX="audit-test"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Creating all test resources for auditor"
echo "  Region: East US 2"
echo "  VM size: $VM_SIZE (2 vCPUs — confirmed available)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── 1. Resource group ─────────────────────────────────────────
echo "[1/7] Creating resource group..."
az group create \
  --name "$RG" \
  --location "$LOCATION" \
  --output none
echo "      ✅ $RG (eastus2)"

# ── 2. Orphaned disks ────────────────────────────────────────
echo "[2/7] Creating unattached managed disks (orphaned)..."
az disk create \
  --resource-group "$RG" \
  --name "${PREFIX}-orphan-disk-01" \
  --size-gb 128 --sku Premium_LRS \
  --location "$LOCATION" --output none

az disk create \
  --resource-group "$RG" \
  --name "${PREFIX}-orphan-disk-02" \
  --size-gb 256 --sku Premium_LRS \
  --location "$LOCATION" --output none

echo "      ✅ ${PREFIX}-orphan-disk-01  128GB  ~\$19.71/month"
echo "      ✅ ${PREFIX}-orphan-disk-02  256GB  ~\$39.42/month"

# ── 3. Orphaned public IP ─────────────────────────────────────
echo "[3/7] Creating unassigned public IP (orphaned)..."
az network public-ip create \
  --resource-group "$RG" \
  --name "${PREFIX}-orphan-ip-01" \
  --sku Standard --allocation-method Static \
  --location "$LOCATION" --output none
echo "      ✅ ${PREFIX}-orphan-ip-01  ~\$3.65/month"

# ── 4. Empty resource group ───────────────────────────────────
echo "[4/7] Creating empty resource group (orphaned)..."
az group create \
  --name "$EMPTY_RG" \
  --location "$LOCATION" --output none
echo "      ✅ $EMPTY_RG"

# ── 5. VNet ───────────────────────────────────────────────────
echo "[5/7] Creating VNet..."
az network vnet create \
  --resource-group "$RG" \
  --name "${PREFIX}-vnet" \
  --address-prefix 10.0.0.0/16 \
  --subnet-name default \
  --subnet-prefix 10.0.0.0/24 \
  --location "$LOCATION" --output none
echo "      ✅ ${PREFIX}-vnet"

# ── 6. Stopped VM ────────────────────────────────────────────
# Create → deallocate immediately → frees 2 cores for oversized VM
echo "[6/7] Creating VM to stop (orphaned stopped VM)..."
echo "      Creating $VM_SIZE — will deallocate to free quota..."
az vm create \
  --resource-group "$RG" \
  --name "${PREFIX}-stopped-vm" \
  --image Ubuntu2204 \
  --size "$VM_SIZE" \
  --admin-username azureuser \
  --generate-ssh-keys \
  --vnet-name "${PREFIX}-vnet" \
  --subnet default \
  --public-ip-address "" \
  --location "$LOCATION" \
  --output none

az vm deallocate \
  --resource-group "$RG" \
  --name "${PREFIX}-stopped-vm" \
  --output none

echo "      ✅ ${PREFIX}-stopped-vm  stopped  ~\$4/month OS disk"
echo "      ℹ️  Deallocated — 2 vCPU cores free for next VM"

# ── 7. Oversized running VM ───────────────────────────────────
echo "[7/7] Creating oversized running VM (right-sizing target)..."
az vm create \
  --resource-group "$RG" \
  --name "${PREFIX}-oversized-vm" \
  --image Ubuntu2204 \
  --size "$VM_SIZE" \
  --admin-username azureuser \
  --generate-ssh-keys \
  --vnet-name "${PREFIX}-vnet" \
  --subnet default \
  --public-ip-address "" \
  --location "$LOCATION" \
  --output none

echo "      Running simple script on VM..."
az vm run-command invoke \
  --resource-group "$RG" \
  --name "${PREFIX}-oversized-vm" \
  --command-id RunShellScript \
  --scripts "
    echo '=== VM is running ==='
    echo 'Hostname:' \$(hostname)
    echo 'CPU cores:' \$(nproc)
    echo 'Memory:' \$(free -h | grep Mem)
    echo 'Uptime:' \$(uptime)
    echo ''
    echo '=== Simulating low-CPU workload ==='
    for i in {1..3}; do
      echo \"Check \$i: CPU idle — underutilised VM at \$(date)\"
      sleep 1
    done
    echo 'Done — VM running but oversized'
  " --output table 2>/dev/null || true

echo "      ✅ ${PREFIX}-oversized-vm  $VM_SIZE  running"
echo "         Mock metrics 8% CPU → auditor will flag for right-sizing"

# ── Summary ───────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ All test resources created"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  ORPHANED:"
echo "  · ${PREFIX}-orphan-disk-01   128GB disk   ~\$19.71/month"
echo "  · ${PREFIX}-orphan-disk-02   256GB disk   ~\$39.42/month"
echo "  · ${PREFIX}-orphan-ip-01     public IP    ~\$ 3.65/month"
echo "  · $EMPTY_RG       empty RG     ~\$ 0.00/month"
echo "  · ${PREFIX}-stopped-vm       stopped VM   ~\$ 4.00/month"
echo ""
echo "  RIGHT-SIZING (mock 8% CPU):"
echo "  · ${PREFIX}-oversized-vm     D2as_v7 → D2alds_v7  ~\$20/month saving"
echo ""
echo "  Next:"
echo "  1. bash run-local-test.sh"
echo "  2. Actions → Resource Audit → Run workflow"
echo "  3. bash cleanup-test-resources.sh"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
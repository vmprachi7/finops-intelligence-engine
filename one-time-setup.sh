#!/bin/bash
# ═══════════════════════════════════════════════════════════
# FINOPS ENGINE — ONE-TIME CLUSTER SETUP
# Passwordless — reads all secrets from environment variables
# These are already in your ~/.zshrc from the platform setup
# ═══════════════════════════════════════════════════════════
set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Checking required environment variables"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Validate all required vars are set ───────────────────────
MISSING=()
[[ -z "$ARM_CLIENT_ID" ]]       && MISSING+=("ARM_CLIENT_ID")
[[ -z "$ARM_CLIENT_SECRET" ]]   && MISSING+=("ARM_CLIENT_SECRET")
[[ -z "$ARM_TENANT_ID" ]]       && MISSING+=("ARM_TENANT_ID")
[[ -z "$ARM_SUBSCRIPTION_ID" ]] && MISSING+=("ARM_SUBSCRIPTION_ID")
[[ -z "$GROQ_API_KEY" ]]        && MISSING+=("GROQ_API_KEY")

if [ ${#MISSING[@]} -gt 0 ]; then
  echo ""
  echo "❌ Missing environment variables:"
  for var in "${MISSING[@]}"; do
    echo "   export ${var}=your-value"
  done
  echo ""
  echo "Add missing vars to ~/.zshrc then: source ~/.zshrc"
  exit 1
fi

echo "✅ All environment variables present"
echo ""

# ── Step 1: Connect to AKS ────────────────────────────────────
echo "Step 1 — Connecting to AKS cluster..."
az aks get-credentials \
  --resource-group devops-platform-rg \
  --name devops-platform-aks \
  --overwrite-existing
kubectl get nodes
echo "✅ Cluster connected"
echo ""

# ── Step 2: Create namespace ──────────────────────────────────
echo "Step 2 — Creating namespace..."
kubectl create namespace finops-engine \
  --dry-run=client -o yaml | kubectl apply -f -
echo "✅ Namespace ready"
echo ""

# ── Step 3: Create ACR pull secret ───────────────────────────
echo "Step 3 — Creating ACR pull secret..."
ACR_PASSWORD=$(az acr credential show \
  --name devopsplatformacr \
  --query passwords[0].value -o tsv)

kubectl create secret docker-registry acr-secret \
  --namespace finops-engine \
  --docker-server=devopsplatformacr.azurecr.io \
  --docker-username=devopsplatformacr \
  --docker-password="$ACR_PASSWORD" \
  --dry-run=client -o yaml | kubectl apply -f -
echo "✅ ACR secret created"
echo ""

# ── Step 4: Create app secrets from env vars ──────────────────
echo "Step 4 — Creating app secrets from environment variables..."
kubectl create secret generic finops-secrets \
  --namespace finops-engine \
  --from-literal=GROQ_API_KEY="$GROQ_API_KEY" \
  --from-literal=AZURE_SUBSCRIPTION_ID="$ARM_SUBSCRIPTION_ID" \
  --from-literal=AZURE_TENANT_ID="$ARM_TENANT_ID" \
  --from-literal=AZURE_CLIENT_ID="$ARM_CLIENT_ID" \
  --from-literal=AZURE_CLIENT_SECRET="$ARM_CLIENT_SECRET" \
  --dry-run=client -o yaml | kubectl apply -f -
echo "✅ App secrets created — nothing printed to terminal"
echo ""

# ── Step 5: Register finops repo in ArgoCD ───────────────────
echo "Step 5 — Registering finops repo in ArgoCD..."
ARGOCD_PASS=$(kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d)

kubectl port-forward svc/argocd-server -n argocd 8090:443 &
PF_PID=$!
sleep 8

argocd login localhost:8090 \
  --username admin \
  --password "$ARGOCD_PASS" \
  --insecure

argocd repo add https://github.com/vmprachi7/finops-intelligence-engine || true
echo "✅ Repo registered"
echo ""

# ── Step 6: Apply ArgoCD Application CRD ─────────────────────
echo "Step 6 — Applying ArgoCD Application CRD..."
kubectl apply -f k8s/manifests.yaml
sleep 5
argocd app list
kill $PF_PID 2>/dev/null || true
echo ""

# ── Step 7: Add OIDC federated credentials ───────────────────
echo "Step 7 — Adding OIDC federated credentials for finops repo..."
SP_OBJECT_ID=$(az ad sp show --id "$ARM_CLIENT_ID" --query id -o tsv)

az ad app federated-credential create \
  --id "$SP_OBJECT_ID" \
  --parameters "{
    \"name\": \"github-finops-main\",
    \"issuer\": \"https://token.actions.githubusercontent.com\",
    \"subject\": \"repo:vmprachi7/finops-intelligence-engine:ref:refs/heads/main\",
    \"audiences\": [\"api://AzureADTokenExchange\"]
  }" 2>/dev/null || echo "ℹ️  github-finops-main already exists"

az ad app federated-credential create \
  --id "$SP_OBJECT_ID" \
  --parameters "{
    \"name\": \"github-finops-pr\",
    \"issuer\": \"https://token.actions.githubusercontent.com\",
    \"subject\": \"repo:vmprachi7/finops-intelligence-engine:pull_request\",
    \"audiences\": [\"api://AzureADTokenExchange\"]
  }" 2>/dev/null || echo "ℹ️  github-finops-pr already exists"

echo "✅ OIDC credentials configured"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ One-time setup complete"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "GitHub Secrets to add:"
echo "  Repo: github.com/vmprachi7/finops-intelligence-engine"
echo "  → Settings → Secrets and variables → Actions"
echo ""
echo "  ARM_CLIENT_ID       = $ARM_CLIENT_ID"
echo "  ARM_TENANT_ID       = $ARM_TENANT_ID"
echo "  ARM_SUBSCRIPTION_ID = $ARM_SUBSCRIPTION_ID"
echo "  GROQ_API_KEY        = (copy from your .env file)"
echo ""
echo "  NOTE: ARM_CLIENT_SECRET is NOT needed in GitHub"
echo "        Pipeline uses OIDC — no password stored"
echo ""
echo "Then push code → pipeline runs automatically"
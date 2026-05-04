# GitHub Secrets — finops-intelligence-engine repo
# Add at: github.com/vmprachi7/finops-intelligence-engine
# → Settings → Secrets and variables → Actions → New repository secret

# ── Required for OIDC login to Azure ─────────────────────────
# (same values as devops-platform-foundation repo)

# ARM_CLIENT_ID
az ad sp show --display-name terraform-sp --query appId -o tsv

# ARM_TENANT_ID
az account show --query tenantId -o tsv

# ARM_SUBSCRIPTION_ID
az account show --query id -o tsv

# ── Required for app secrets (injected into cluster) ─────────

# GROQ_API_KEY
# Your Groq key from console.groq.com
# Value: gsk_your-key-here

# ── Required for pipeline to push manifest back to repo ───────
# GITHUB_TOKEN is automatic — no action needed

# ── OIDC federated credentials ────────────────────────────────
# Run these once to allow the finops pipeline to authenticate to Azure

SP_OBJECT_ID=$(az ad sp show --display-name "terraform-sp" --query id -o tsv)

# For pushes to main
az ad app federated-credential create \
  --id "$SP_OBJECT_ID" \
  --parameters '{
    "name": "github-finops-main",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:vmprachi7/finops-intelligence-engine:ref:refs/heads/main",
    "audiences": ["api://AzureADTokenExchange"]
  }'

# For pull requests
az ad app federated-credential create \
  --id "$SP_OBJECT_ID" \
  --parameters '{
    "name": "github-finops-pr",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:vmprachi7/finops-intelligence-engine:pull_request",
    "audiences": ["api://AzureADTokenExchange"]
  }'

# Verify both credentials exist
az ad app federated-credential list --id "$SP_OBJECT_ID" --output table

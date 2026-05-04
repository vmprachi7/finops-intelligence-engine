# Project 2 — Complete Build & Deploy Guide
# Run everything in this exact order. Nothing skipped.

# ═══════════════════════════════════════════════════════════
# PHASE 1: LOCAL DEVELOPMENT (no Azure cluster needed)
# Goal: dashboard running at localhost:8501 with mock data
# Time: ~30 minutes
# ═══════════════════════════════════════════════════════════

# ── Step 1: Create GitHub repo ───────────────────────────────
# Go to github.com → New repository
# Name: finops-intelligence-engine
# Visibility: Public
# Add README: yes
# Then clone it:

git clone https://github.com/YOUR_USERNAME/finops-intelligence-engine.git
cd finops-intelligence-engine

# ── Step 2: Create folder structure ──────────────────────────

mkdir -p app mock_data k8s tests docs/adr .github/workflows

touch app/__init__.py
touch app/main.py
touch app/config.py
touch app/cost_fetcher.py
touch app/anomaly_detector.py
touch app/ai_advisor.py
touch tests/__init__.py
touch tests/test_anomaly_detector.py

# ── Step 3: Copy all code files ──────────────────────────────
# Download all files from the guide and copy them:
#
# app/config.py           → from guide
# app/cost_fetcher.py     → from guide
# app/anomaly_detector.py → from guide
# app/ai_advisor.py       → from guide
# app/main.py             → from guide
# tests/test_anomaly_detector.py → from guide
# k8s/manifests.yaml      → from guide
# .github/workflows/finops-ci-cd.yml → from guide
# Dockerfile              → from guide
# requirements.txt        → from guide
# README.md               → from guide

# ── Step 4: Create .gitignore ────────────────────────────────

cat > .gitignore << 'EOF'
.env
venv/
__pycache__/
*.pyc
.pytest_cache/
mock_data/sample_costs.json
*.egg-info/
dist/
.streamlit/
EOF

# ── Step 5: Get Anthropic API key ────────────────────────────
# 1. Go to console.anthropic.com
# 2. Sign up with personal email
# 3. Go to API Keys → Create key
# 4. Copy the key (starts with sk-ant-...)
# Free tier gives $5 credit — more than enough for this project

# ── Step 6: Create .env file ─────────────────────────────────

cat > .env << 'EOF'
# For local dev — uses generated mock data, no Azure needed
USE_MOCK_DATA=true
ANTHROPIC_API_KEY=sk-ant-your-key-here

# Anomaly detection settings
LOOKBACK_DAYS=30
ANOMALY_THRESHOLD_PCT=30

# Budget thresholds
DAILY_BUDGET_USD=10
MONTHLY_BUDGET_USD=100
EOF

# ── Step 7: Set up Python virtual environment ─────────────────

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# ── Step 8: Run tests to confirm everything works ────────────

USE_MOCK_DATA=true pytest tests/ -v

# EXPECTED OUTPUT:
# test_no_anomalies_on_stable_data PASSED
# test_detects_cost_spike PASSED
# test_anomaly_severity_classification PASSED
# ... all PASSED

# ── Step 9: Run the dashboard ────────────────────────────────

streamlit run app/main.py

# Open: http://localhost:8501
# You should see:
# - KPI metrics row (MTD spend, yesterday, trend, anomalies, projected)
# - Daily spend area chart with anomaly markers
# - Budget progress bar
# - Pie chart of cost by service
# - Anomaly cards on the right
# - AI recommendations button at the bottom

# ── Step 10: Test the AI recommendations ─────────────────────
# In the dashboard, click "Generate AI recommendations"
# Claude will analyse the mock anomalies and return specific advice
# This confirms your Anthropic API key is working

# ── Step 11: Push to GitHub ───────────────────────────────────

git add .
git commit -m "feat: complete FinOps Intelligence Engine implementation"
git push

# ═══════════════════════════════════════════════════════════
# PHASE 2: CONNECT REAL AZURE DATA
# Goal: dashboard showing your actual Azure costs
# Time: ~20 minutes
# Prerequisites: Azure account with some spend data
# ═══════════════════════════════════════════════════════════

# ── Step 12: Verify Azure Cost Management API access ─────────

# The Service Principal you created for Terraform needs an extra role
# to read cost data:

az role assignment create \
  --assignee "YOUR_SP_APP_ID" \
  --role "Cost Management Reader" \
  --scope "/subscriptions/YOUR_SUBSCRIPTION_ID"

# Verify the role was assigned:
az role assignment list \
  --assignee "YOUR_SP_APP_ID" \
  --output table

# ── Step 13: Update .env for real data ───────────────────────

cat > .env << 'EOF'
USE_MOCK_DATA=false
AZURE_SUBSCRIPTION_ID=your-subscription-id
AZURE_TENANT_ID=your-tenant-id
AZURE_CLIENT_ID=your-sp-appId
AZURE_CLIENT_SECRET=your-sp-password
ANTHROPIC_API_KEY=sk-ant-your-key-here
LOOKBACK_DAYS=30
ANOMALY_THRESHOLD_PCT=30
DAILY_BUDGET_USD=10
MONTHLY_BUDGET_USD=100
EOF

# ── Step 14: Run with real data ───────────────────────────────

streamlit run app/main.py

# NOTE: If your Azure account is brand new and has minimal spend,
# the charts will show mostly zeros — that's fine for the portfolio.
# The mock data mode is what you'll use for demos anyway.
# Real data is for showing "I know how to connect to Azure APIs"

# ═══════════════════════════════════════════════════════════
# PHASE 3: DOCKERISE + DEPLOY TO AKS
# Goal: app running as a pod in your AKS cluster
# Time: ~30 minutes
# Prerequisites: Foundation cluster running (terraform applied)
# ═══════════════════════════════════════════════════════════

# ── Step 15: Recreate foundation cluster (if destroyed) ──────

cd ../devops-platform-foundation/terraform/environments/dev
terraform apply -auto-approve

az aks get-credentials \
  --resource-group devops-platform-rg \
  --name devops-platform-aks

# Reinstall ArgoCD
kubectl create namespace argocd
kubectl apply -n argocd \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/name=argocd-server \
  -n argocd --timeout=180s

# Reinstall observability
kubectl create namespace monitoring
helm install kube-prometheus-stack \
  prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --set grafana.adminPassword=admin123
helm install loki grafana/loki-stack \
  --namespace monitoring \
  --set grafana.enabled=false \
  --set prometheus.enabled=false

cd ../../../..
cd finops-intelligence-engine

# ── Step 16: Build Docker image ───────────────────────────────

docker build -t finops-engine:local .

# Test it locally first:
docker run -p 8501:8501 \
  -e USE_MOCK_DATA=true \
  -e ANTHROPIC_API_KEY=your-key \
  finops-engine:local

# Open http://localhost:8501 — should work identically to before

# ── Step 17: Push image to ACR ────────────────────────────────

az acr login --name devopsplatformacr

docker tag finops-engine:local \
  devopsplatformacr.azurecr.io/finops-engine:v1.0.0

docker tag finops-engine:local \
  devopsplatformacr.azurecr.io/finops-engine:latest

docker push devopsplatformacr.azurecr.io/finops-engine:v1.0.0
docker push devopsplatformacr.azurecr.io/finops-engine:latest

# ── Step 18: Create K8s secrets ───────────────────────────────

kubectl create namespace finops-engine

# Application secrets
kubectl create secret generic finops-secrets \
  --namespace finops-engine \
  --from-literal=AZURE_SUBSCRIPTION_ID=your-sub-id \
  --from-literal=AZURE_TENANT_ID=your-tenant-id \
  --from-literal=AZURE_CLIENT_ID=your-client-id \
  --from-literal=AZURE_CLIENT_SECRET=your-client-secret \
  --from-literal=ANTHROPIC_API_KEY=your-anthropic-key

# ACR image pull secret
ACR_PASSWORD=$(az acr credential show \
  --name devopsplatformacr \
  --query passwords[0].value -o tsv)

kubectl create secret docker-registry acr-secret \
  --namespace finops-engine \
  --docker-server=devopsplatformacr.azurecr.io \
  --docker-username=devopsplatformacr \
  --docker-password=$ACR_PASSWORD

# ── Step 19: Update manifest with your GitHub username ────────

# Edit k8s/manifests.yaml — find this line:
#   repoURL: https://github.com/YOUR_USERNAME/finops-intelligence-engine
# Replace YOUR_USERNAME with your actual GitHub username

sed -i '' 's/YOUR_USERNAME/your-actual-github-username/g' k8s/manifests.yaml

# Also update the image name in deployment to use USE_MOCK_DATA=true
# for the demo (so it works without real Azure credentials in cluster)
# Edit k8s/manifests.yaml → configmap → set USE_MOCK_DATA: "true"

# ── Step 20: Deploy to AKS ────────────────────────────────────

kubectl apply -f k8s/manifests.yaml

# Watch pods come up (takes ~60 seconds)
kubectl get pods -n finops-engine -w

# EXPECTED:
# NAME                             READY   STATUS    RESTARTS   AGE
# finops-engine-7d9f8b-xxxxx       1/1     Running   0          60s

# ── Step 21: Access the dashboard ────────────────────────────

kubectl port-forward svc/finops-engine -n finops-engine 8080:80
# Open: http://localhost:8080

# ── Step 22: Add ArgoCD Application for GitOps management ────

# Apply the ArgoCD application manifest
# (already included in k8s/manifests.yaml — the last resource)
kubectl apply -f k8s/manifests.yaml

# Check ArgoCD
kubectl port-forward svc/argocd-server -n argocd 8090:443 &
argocd admin initial-password -n argocd
argocd login localhost:8090 --username admin --insecure
argocd app list

# EXPECTED:
# NAME           CLUSTER  NAMESPACE      PROJECT  STATUS  HEALTH
# finops-engine  ...      finops-engine  default  Synced  Healthy

# ── Step 23: Verify full deployment ──────────────────────────

kubectl get pods -n finops-engine
kubectl get svc  -n finops-engine
kubectl describe deployment finops-engine -n finops-engine
kubectl logs -n finops-engine -l app=finops-engine --tail=20

# ═══════════════════════════════════════════════════════════
# PHASE 4: GITHUB ACTIONS CI/CD
# Goal: push to main → image built → deployed to AKS
# Time: ~20 minutes
# ═══════════════════════════════════════════════════════════

# ── Step 24: Add GitHub Secrets ───────────────────────────────
# Go to: github.com/YOUR_USERNAME/finops-intelligence-engine
# Settings → Secrets and variables → Actions → New repository secret

# Add these secrets:
# AZURE_SUBSCRIPTION_ID  → your subscription ID
# AZURE_TENANT_ID        → your tenant ID
# AZURE_CLIENT_ID        → your SP appId
# AZURE_CLIENT_SECRET    → your SP password
# ANTHROPIC_API_KEY      → your Anthropic key
# ACR_USERNAME           → devopsplatformacr
# ACR_PASSWORD           → (from: az acr credential show --name devopsplatformacr --query passwords[0].value -o tsv)

# For AZURE_CREDENTIALS (needed by azure/login action):
az ad sp create-for-rbac \
  --name "github-actions-finops-sp" \
  --role="Contributor" \
  --scopes="/subscriptions/YOUR_SUBSCRIPTION_ID" \
  --sdk-auth
# Copy the entire JSON output → paste as AZURE_CREDENTIALS secret

# ── Step 25: Test the pipeline ────────────────────────────────

# Make a small change to trigger the pipeline:
echo "# Pipeline test $(date)" >> README.md
git add README.md
git commit -m "ci: test GitHub Actions pipeline"
git push

# Go to: github.com/YOUR_USERNAME/finops-intelligence-engine/actions
# Watch: test → build-push → deploy jobs run green

# ═══════════════════════════════════════════════════════════
# SCREENSHOTS TO TAKE (while cluster is running)
# ═══════════════════════════════════════════════════════════

# 1. Dashboard overview — full page at http://localhost:8080
#    Shows: KPI metrics, charts, anomaly cards

# 2. AI recommendations panel
#    Click "Generate AI recommendations" → screenshot the output
#    Shows: Claude's specific, actionable advice

# 3. Anomaly cards section
#    Shows: color-coded critical/warning/info cards

# 4. ArgoCD — finops-engine app Synced + Healthy
#    https://localhost:8090 → finops-engine tile

# 5. kubectl get pods -n finops-engine
#    Terminal showing pod Running

# 6. GitHub Actions — green pipeline
#    github.com/YOUR_USERNAME/finops-intelligence-engine/actions

# 7. Grafana — add finops namespace to dashboard
#    http://localhost:3000 → Kubernetes / Compute Resources / Namespace
#    Select namespace: finops-engine
#    Shows: CPU + memory for the running pod

# ═══════════════════════════════════════════════════════════
# TEARDOWN (save Azure credits)
# ═══════════════════════════════════════════════════════════

# When done:
cd ../devops-platform-foundation/terraform/environments/dev
terraform destroy -auto-approve

# To recreate everything in one paste:
terraform apply -auto-approve && \
az aks get-credentials --resource-group devops-platform-rg --name devops-platform-aks && \
kubectl create namespace argocd && \
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml && \
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=argocd-server -n argocd --timeout=180s && \
kubectl create namespace monitoring && \
helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring --set grafana.adminPassword=admin123 && \
helm install loki grafana/loki-stack --namespace monitoring \
  --set grafana.enabled=false --set prometheus.enabled=false && \
cd ../../../../finops-intelligence-engine && \
kubectl create namespace finops-engine && \
kubectl create secret generic finops-secrets --namespace finops-engine \
  --from-literal=AZURE_SUBSCRIPTION_ID=$ARM_SUBSCRIPTION_ID \
  --from-literal=AZURE_TENANT_ID=$ARM_TENANT_ID \
  --from-literal=AZURE_CLIENT_ID=$ARM_CLIENT_ID \
  --from-literal=AZURE_CLIENT_SECRET=$ARM_CLIENT_SECRET \
  --from-literal=ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY && \
ACR_PW=$(az acr credential show --name devopsplatformacr --query passwords[0].value -o tsv) && \
kubectl create secret docker-registry acr-secret --namespace finops-engine \
  --docker-server=devopsplatformacr.azurecr.io \
  --docker-username=devopsplatformacr \
  --docker-password=$ACR_PW && \
kubectl apply -f k8s/manifests.yaml && \
kubectl get pods -A

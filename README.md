# FinOps Intelligence Engine

> Real-time Azure cost anomaly detection with AI-powered recommendations.
> Detects spend spikes using rolling statistical analysis, then uses Groq AI (Llama 3.1)
> to generate specific, actionable optimisation advice — not just alerts.

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python)
![Streamlit](https://img.shields.io/badge/Streamlit-1.32-FF4B4B?logo=streamlit)
![Groq](https://img.shields.io/badge/Groq-Llama_3.1-orange)
![Azure](https://img.shields.io/badge/Azure-Cost_API-0078D4?logo=microsoftazure)
![AKS](https://img.shields.io/badge/Deployed_on-AKS-326CE5?logo=kubernetes)

---

## What problem this solves

Cloud bills spike silently. Teams find out at month-end when nothing can be
done. This engine detects anomalies daily, explains them in plain English,
and suggests specific fixes — before the invoice lands.

---

## Architecture

```
Azure Cost Management API (or mock data)
         │
         ▼
  cost_fetcher.py       Fetches daily cost data per service
         │
         ▼
  anomaly_detector.py   Rolling 7-day average + threshold detection
         │
         ▼
  ai_advisor.py         Groq API (Llama 3.1) → specific recommendations
         │
         ▼
  main.py (Streamlit)   Dashboard: charts + anomaly cards + AI panel
         │
         ▼
  AKS (Phase 2)         Deployed as pod via ArgoCD GitOps
```

---

## Phase 1 — Run locally (start here)

### Step 1 — Get a free Groq API key

1. Go to [console.groq.com](https://console.groq.com)
2. Sign up free — no credit card required
3. Go to **API Keys → Create key**
4. Copy the key (starts with `gsk_...`)`)
5. Completely free — no credit card, no limits for learning

### Step 2 — Clone and set up Python environment

```bash
git clone https://github.com/vmprachi7/finops-intelligence-engine.git
cd finops-intelligence-engine

# Create virtual environment
python3 -m venv venv
source venv/bin/activate   # Mac/Linux

# Install dependencies
pip install -r requirements.txt
```

### Step 3 — Create your .env file

```bash
cp .env.example .env
```

Open `.env` and set:

```bash
ANTHROPIC_API_KEY=sk-ant-your-key-here
USE_MOCK_DATA=true      # keep this true until you have Azure credentials
```

Everything else can stay as-is for local development.

### Step 4 — Create the mock_data folder

```bash
mkdir -p mock_data
```

The app auto-generates realistic mock data on first run (7 Azure services,
30 days, with deliberate spikes for demo purposes).

### Step 5 — Run the dashboard

```bash
streamlit run app/main.py
```

Open **http://localhost:8501**

You should see:
- KPI metrics row (MTD spend, yesterday, trend, anomaly count, projected)
- Daily spend area chart with red lines on anomaly dates
- Budget progress bar
- Service breakdown pie chart
- Anomaly cards (colour-coded by severity)
- AI recommendations button at the bottom

### Step 6 — Test the AI recommendations

Click **"✨ Generate AI recommendations"**

Groq AI will analyse the mock anomalies and return specific, actionable advice.
This confirms your API key is working correctly.

### Step 7 — Run tests

```bash
USE_MOCK_DATA=true pytest tests/ -v
```

All tests should pass. You should see 13 tests in total.

### Step 8 — Push to GitHub

```bash
# Verify .env is in .gitignore (it is — never commit secrets)
git status

git add .
git commit -m "feat: complete FinOps Intelligence Engine implementation"
git push
```

---

## Phase 2 — Connect real Azure cost data

Skip this section if you just want the local demo working first.

### Azure roles required

The Service Principal from the platform project needs one extra role to
read cost data:

```bash
az role assignment create \
  --assignee "YOUR_SP_APP_ID" \
  --role "Cost Management Reader" \
  --scope "/subscriptions/YOUR_SUBSCRIPTION_ID"

# Verify
az role assignment list --assignee "YOUR_SP_APP_ID" --output table
```

### Update .env for real data

```bash
USE_MOCK_DATA=false
AZURE_SUBSCRIPTION_ID=your-subscription-id
AZURE_TENANT_ID=your-tenant-id
AZURE_CLIENT_ID=your-sp-appId
AZURE_CLIENT_SECRET=your-sp-password
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

Run again — `streamlit run app/main.py` — now showing real Azure costs.

---

## Phase 3 — Deploy to AKS

### Prerequisites

- Platform foundation cluster running (`devops-platform-aks`)
- ACR provisioned (`devopsplatformacr`)
- `kubectl` configured pointing at the cluster

### Step 1 — Build and push Docker image

```bash
az acr login --name devopsplatformacr

docker build -t devopsplatformacr.azurecr.io/finops-engine:latest .
docker push devopsplatformacr.azurecr.io/finops-engine:latest
```

### Step 2 — Create secrets in cluster

```bash
kubectl create namespace finops-engine

kubectl create secret generic finops-secrets \
  --namespace finops-engine \
  --from-literal=AZURE_SUBSCRIPTION_ID=your-sub-id \
  --from-literal=AZURE_TENANT_ID=your-tenant-id \
  --from-literal=AZURE_CLIENT_ID=your-client-id \
  --from-literal=AZURE_CLIENT_SECRET=your-client-secret \
  --from-literal=ANTHROPIC_API_KEY=your-api-key
```

### Step 3 — Register finops repo in ArgoCD

```bash
PASS=$(kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d)

kubectl port-forward svc/argocd-server -n argocd 8080:443 &
sleep 5

argocd login localhost:8080 --username admin --password "$PASS" --insecure

# Public repo — no credentials needed
argocd repo add https://github.com/vmprachi7/finops-intelligence-engine
```

Or add the ArgoCD Application CRD to the platform repo's
`gitops/argocd-apps/finops-engine.yaml` — ArgoCD will pick it up
automatically on next sync.

### Step 4 — Deploy

```bash
kubectl apply -f k8s/manifests.yaml
kubectl get pods -n finops-engine -w
```

### Step 5 — Access the dashboard

```bash
kubectl port-forward svc/finops-engine -n finops-engine 8080:80
# Open: http://localhost:8080
```

---

## GitHub Actions CI/CD

The pipeline in `.github/workflows/finops-ci-cd.yml` does:

1. **test** — runs `pytest` on every push and PR
2. **build-push** — builds Docker image, tags with short SHA, pushes to ACR
3. **deploy** — applies K8s manifests, updates image tag, waits for rollout

### Secrets required

| Secret | Source |
|---|---|
| `ARM_CLIENT_ID` | SP appId |
| `ARM_CLIENT_SECRET` | SP password |
| `ARM_TENANT_ID` | tenant ID |
| `ARM_SUBSCRIPTION_ID` | subscription ID |
| `GROQ_API_KEY` | from console.groq.com (free) |

OIDC is configured — no `AZURE_CREDENTIALS` JSON secret needed.
See the platform repo for federated credential setup.

---

## Architecture Decision Records

### ADR-001: Streamlit over Flask/FastAPI

Streamlit renders DataFrames, Plotly charts, and markdown natively.
For a data dashboard, this means 100% focus on logic, not UI code.
Trade-off: not suitable for high-concurrency production. For a FinOps
internal tool with ~10 concurrent users, this is not a concern.

### ADR-002: Rolling average over ML model

Cost data has low dimensionality. A statistical approach is transparent —
engineers understand exactly why a day was flagged. Tunable via config
without retraining. Trade-off: will miss slow-drift anomalies.

### ADR-003: Groq over OpenAI

Groq's free tier with Llama 3.1 is fast, capable, and costs nothing.
No API cost — ideal for learning projects and portfolios.

---

## Interview talking points

**On the problem:**
> "Cloud bills spike silently — teams find out at month-end when nothing
> can be done. I built a tool that detects anomalies daily and explains
> them in plain English using AI."

**On anomaly detection:**
> "I chose rolling 7-day average over an ML model deliberately. The logic
> is transparent — a senior engineer can look at it and understand exactly
> why a day was flagged. Black-box models are harder to trust for cost
> alerts where false positives have real consequences."

**On the AI layer:**
> "The AI doesn't just repeat the anomaly back to you. It reasons about the
> specific service — AKS spike means suggesting spot instances, storage
> spike means lifecycle policies. The recommendations are specific and
> actionable, not generic."

**On deployment:**
> "It runs as a pod in the same AKS cluster as the platform foundation.
> Deployed via ArgoCD — I pushed the k8s manifest to GitHub and ArgoCD
> synced it. The CI/CD pipeline builds the Docker image, pushes to ACR,
> and updates the deployment. Zero manual steps."

---

*Part of the DevOps Platform portfolio by Prachi*
*[devops-platform-foundation](https://github.com/vmprachi7/devops-platform-foundation)*
*[LinkedIn](https://www.linkedin.com/in/prachi-v/) · [GitHub](https://github.com/vmprachi7)*
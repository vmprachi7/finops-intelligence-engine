"""
Azure Resource Auditor
Two categories of findings:
  1. ORPHANED — resources you pay for but don't use
  2. RIGHT-SIZING — resources running but oversized

Orphaned resources:
  - Unattached managed disks
  - Unassigned public IP addresses
  - Empty resource groups
  - Stopped (deallocated) VMs still paying for OS disk
  - Unused load balancers (no backend pool members)

Right-sizing (uses Azure Monitor 7-day avg metrics):
  - VMs with avg CPU < 20% and avg memory < 30%
  - AKS node pools with avg node CPU < 30%
  - Managed disks on Premium SKU but low IOPS usage
"""
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.monitor import MonitorManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.containerservice import ContainerServiceClient
from openai import OpenAI


# ── Azure pricing (USD/month, approx) ────────────────────────
DISK_COST_PER_GB        = 0.154   # Premium SSD per GB
PUBLIC_IP_COST          = 3.65    # Unassigned static public IP
STOPPED_VM_OS_DISK      = 4.00    # Stopped VM OS disk cost
LB_COST                 = 18.25   # Standard Load Balancer base

# VM SKU pricing (USD/month) — common sizes, Central India
VM_PRICING = {
    "Standard_B1s":    7.59,
    "Standard_B2s":   30.37,
    "Standard_B2ms":  52.56,
    "Standard_B4ms":  105.12,
    "Standard_B2ps_v2": 28.54,
    "Standard_D2s_v3":  70.08,
    "Standard_D4s_v3": 140.16,
    "Standard_D8s_v3": 280.32,
    "Standard_D2as_v4": 62.78,
    "Standard_D4as_v4": 125.56,
}

# Right-size suggestions (current → recommended)
VM_RIGHTSIZING = {
    "Standard_D4s_v3":  ("Standard_D2s_v3",   70.08),
    "Standard_D8s_v3":  ("Standard_D4s_v3",  140.16),
    "Standard_D4as_v4": ("Standard_D2as_v4",  62.78),
    "Standard_B4ms":    ("Standard_B2ms",      52.56),
    "Standard_B2ms":    ("Standard_B2s",       30.37),
}

# Thresholds for right-sizing
CPU_THRESHOLD_PCT    = 20.0   # avg CPU below this = oversized
MEMORY_THRESHOLD_PCT = 30.0   # avg memory below this = oversized
AKS_CPU_THRESHOLD    = 30.0   # avg node CPU below this = oversized
DISK_IOPS_THRESHOLD  = 20.0   # avg IOPS% below this = consider Standard


# ── Data classes ──────────────────────────────────────────────

@dataclass
class OrphanedResource:
    resource_type:    str
    name:             str
    resource_group:   str
    monthly_cost_usd: float
    details:          str
    recommendation:   str


@dataclass
class RightSizeRecommendation:
    resource_type:      str
    name:               str
    resource_group:     str
    current_sku:        str
    recommended_sku:    str
    current_cost_usd:   float
    recommended_cost_usd: float
    monthly_saving_usd: float
    avg_cpu_pct:        float
    avg_memory_pct:     float
    details:            str


@dataclass
class AuditReport:
    run_date:          str
    subscription_id:   str
    orphaned:          list[OrphanedResource]          = field(default_factory=list)
    rightsizing:       list[RightSizeRecommendation]   = field(default_factory=list)
    total_orphan_savings_usd:    float = 0.0
    total_rightsizing_savings_usd: float = 0.0
    ai_analysis:       str = ""

    @property
    def total_savings_usd(self) -> float:
        return self.total_orphan_savings_usd + self.total_rightsizing_savings_usd

    def add_orphan(self, r: OrphanedResource):
        self.orphaned.append(r)
        self.total_orphan_savings_usd += r.monthly_cost_usd

    def add_rightsizing(self, r: RightSizeRecommendation):
        self.rightsizing.append(r)
        self.total_rightsizing_savings_usd += r.monthly_saving_usd


# ── Credential setup ──────────────────────────────────────────

def get_credential():
    return ClientSecretCredential(
        tenant_id=os.environ["AZURE_TENANT_ID"],
        client_id=os.environ["AZURE_CLIENT_ID"],
        client_secret=os.environ["AZURE_CLIENT_SECRET"],
    )


# ── Azure Monitor helpers ─────────────────────────────────────

def get_avg_metric(
    monitor: MonitorManagementClient,
    resource_id: str,
    metric_name: str,
    days: int = 7,
) -> float:
    """Get average metric value over last N days. Returns -1 if unavailable."""
    try:
        end   = datetime.now(timezone.utc)
        start = end - timedelta(days=days)

        result = monitor.metrics.list(
            resource_id,
            timespan=f"{start.isoformat()}/{end.isoformat()}",
            interval="P1D",
            metricnames=metric_name,
            aggregation="Average",
        )

        values = []
        for metric in result.value:
            for ts in metric.timeseries:
                for dp in ts.data:
                    if dp.average is not None:
                        values.append(dp.average)

        return round(sum(values) / len(values), 2) if values else -1.0
    except Exception:
        return -1.0


# ── Orphaned resource checks ──────────────────────────────────

def check_unattached_disks(compute, report):
    for disk in compute.disks.list():
        if disk.disk_state == "Unattached":
            size_gb = disk.disk_size_gb or 128
            monthly = round(size_gb * DISK_COST_PER_GB, 2)
            report.add_orphan(OrphanedResource(
                resource_type="Managed Disk (Unattached)",
                name=disk.name,
                resource_group=disk.id.split("/")[4],
                monthly_cost_usd=monthly,
                details=f"{size_gb}GB · {disk.sku.name if disk.sku else 'Unknown'}",
                recommendation=f"Delete if not needed — saves ${monthly:.2f}/month",
            ))


def check_unassigned_public_ips(network, report):
    for ip in network.public_ip_addresses.list_all():
        if ip.ip_configuration is None:
            report.add_orphan(OrphanedResource(
                resource_type="Public IP (Unassigned)",
                name=ip.name,
                resource_group=ip.id.split("/")[4],
                monthly_cost_usd=PUBLIC_IP_COST,
                details=f"SKU: {ip.sku.name if ip.sku else 'Basic'} · {ip.public_ip_allocation_method}",
                recommendation=f"Release — saves ${PUBLIC_IP_COST:.2f}/month",
            ))


def check_empty_resource_groups(resource_client, report):
    for rg in resource_client.resource_groups.list():
        resources = list(resource_client.resources.list_by_resource_group(rg.name))
        if len(resources) == 0:
            report.add_orphan(OrphanedResource(
                resource_type="Empty Resource Group",
                name=rg.name,
                resource_group=rg.name,
                monthly_cost_usd=0.0,
                details=f"Region: {rg.location} · 0 resources",
                recommendation="Delete to reduce clutter",
            ))


def check_stopped_vms(compute, report):
    for rg in _list_resource_group_names(compute):
        for vm in compute.virtual_machines.list(rg):
            try:
                statuses = compute.virtual_machines.instance_view(rg, vm.name).statuses
                power = next(
                    (s.display_status for s in statuses
                     if s.code and s.code.startswith("PowerState/")), "unknown"
                )
                if power in ("VM deallocated", "VM stopped"):
                    report.add_orphan(OrphanedResource(
                        resource_type="Stopped VM",
                        name=vm.name,
                        resource_group=rg,
                        monthly_cost_usd=STOPPED_VM_OS_DISK,
                        details=f"Power: {power} · Size: {vm.hardware_profile.vm_size if vm.hardware_profile else 'unknown'}",
                        recommendation=f"Delete or restart — OS disk costs ${STOPPED_VM_OS_DISK:.2f}/month while stopped",
                    ))
            except Exception:
                continue


def check_unused_load_balancers(network, report):
    for lb in network.load_balancers.list_all():
        empty = (
            not lb.backend_address_pools or
            all(not p.backend_ip_configurations for p in lb.backend_address_pools)
        )
        if empty:
            report.add_orphan(OrphanedResource(
                resource_type="Load Balancer (No backends)",
                name=lb.name,
                resource_group=lb.id.split("/")[4],
                monthly_cost_usd=LB_COST,
                details=f"SKU: {lb.sku.name if lb.sku else 'Basic'} · No backend members",
                recommendation=f"Delete if unused — saves ${LB_COST:.2f}/month",
            ))


# ── Right-sizing checks ───────────────────────────────────────

def check_vm_rightsizing(compute, monitor, subscription_id, report):
    """
    Find running VMs with avg CPU < 20% AND avg memory < 30% over 7 days.
    Suggests a smaller SKU where pricing data is available.
    """
    for rg in _list_resource_group_names(compute):
        for vm in compute.virtual_machines.list(rg):
            try:
                # Only check running VMs
                statuses = compute.virtual_machines.instance_view(rg, vm.name).statuses
                power = next(
                    (s.display_status for s in statuses
                     if s.code and s.code.startswith("PowerState/")), "unknown"
                )
                if power != "VM running":
                    continue

                current_sku = vm.hardware_profile.vm_size if vm.hardware_profile else ""
                resource_id = (
                    f"/subscriptions/{subscription_id}/resourceGroups/{rg}"
                    f"/providers/Microsoft.Compute/virtualMachines/{vm.name}"
                )

                avg_cpu = get_avg_metric(
                    monitor, resource_id, "Percentage CPU"
                )
                avg_mem = get_avg_metric(
                    monitor, resource_id, "Available Memory Bytes"
                )

                # Convert available memory bytes to % used
                # (approximate — assumes standard memory per SKU)
                avg_mem_pct = (100 - (avg_mem / (4 * 1024**3) * 100)) if avg_mem > 0 else -1

                if avg_cpu < 0 or avg_cpu >= CPU_THRESHOLD_PCT:
                    continue
                if avg_mem_pct >= MEMORY_THRESHOLD_PCT:
                    continue

                current_cost = VM_PRICING.get(current_sku, 0)
                if current_sku in VM_RIGHTSIZING:
                    rec_sku, rec_cost = VM_RIGHTSIZING[current_sku]
                    saving = round(current_cost - rec_cost, 2)
                else:
                    rec_sku  = "Smaller SKU (review manually)"
                    rec_cost = current_cost * 0.5   # estimate 50% saving
                    saving   = round(current_cost * 0.5, 2)

                if saving <= 0:
                    continue

                report.add_rightsizing(RightSizeRecommendation(
                    resource_type="Virtual Machine",
                    name=vm.name,
                    resource_group=rg,
                    current_sku=current_sku,
                    recommended_sku=rec_sku,
                    current_cost_usd=current_cost,
                    recommended_cost_usd=rec_cost,
                    monthly_saving_usd=saving,
                    avg_cpu_pct=avg_cpu,
                    avg_memory_pct=avg_mem_pct,
                    details=f"7-day avg CPU: {avg_cpu:.1f}% · Avg memory used: {avg_mem_pct:.1f}%",
                ))

            except Exception:
                continue


def check_aks_rightsizing(aks_client, monitor, subscription_id, report):
    """
    Find AKS node pools with avg CPU < 30% — suggest scaling down node count.
    """
    try:
        for cluster in aks_client.managed_clusters.list():
            rg = cluster.id.split("/")[4]
            resource_id = (
                f"/subscriptions/{subscription_id}/resourceGroups/{rg}"
                f"/providers/Microsoft.ContainerService/managedClusters/{cluster.name}"
            )

            avg_cpu = get_avg_metric(
                monitor, resource_id, "node_cpu_usage_percentage"
            )

            if avg_cpu < 0 or avg_cpu >= AKS_CPU_THRESHOLD:
                continue

            # Estimate saving: reducing node count by 1
            node_pools = cluster.agent_pool_profiles or []
            for pool in node_pools:
                if pool.count and pool.count > 1:
                    vm_size    = pool.vm_size or "Standard_B2ps_v2"
                    node_cost  = VM_PRICING.get(vm_size, 30.0)
                    saving     = round(node_cost, 2)

                    report.add_rightsizing(RightSizeRecommendation(
                        resource_type="AKS Node Pool",
                        name=f"{cluster.name}/{pool.name}",
                        resource_group=rg,
                        current_sku=f"{pool.count}x {vm_size}",
                        recommended_sku=f"{pool.count - 1}x {vm_size}",
                        current_cost_usd=node_cost * pool.count,
                        recommended_cost_usd=node_cost * (pool.count - 1),
                        monthly_saving_usd=saving,
                        avg_cpu_pct=avg_cpu,
                        avg_memory_pct=-1,
                        details=f"7-day avg node CPU: {avg_cpu:.1f}% · {pool.count} nodes · {vm_size}",
                    ))
    except Exception:
        pass


def check_disk_rightsizing(compute, monitor, subscription_id, report):
    """
    Find Premium SSD disks with very low IOPS usage — suggest Standard SSD.
    """
    for disk in compute.disks.list():
        if disk.disk_state != "Attached":
            continue
        if not disk.sku or "Premium" not in disk.sku.name:
            continue

        resource_id = disk.id
        avg_iops_pct = get_avg_metric(
            monitor, resource_id, "Disk Read Operations/Sec"
        )

        if avg_iops_pct < 0 or avg_iops_pct >= DISK_IOPS_THRESHOLD:
            continue

        size_gb       = disk.disk_size_gb or 128
        premium_cost  = round(size_gb * DISK_COST_PER_GB, 2)
        standard_cost = round(size_gb * 0.08, 2)   # Standard SSD ~$0.08/GB
        saving        = round(premium_cost - standard_cost, 2)

        if saving <= 0:
            continue

        report.add_rightsizing(RightSizeRecommendation(
            resource_type="Managed Disk (Tier)",
            name=disk.name,
            resource_group=disk.id.split("/")[4],
            current_sku="Premium_LRS",
            recommended_sku="StandardSSD_LRS",
            current_cost_usd=premium_cost,
            recommended_cost_usd=standard_cost,
            monthly_saving_usd=saving,
            avg_cpu_pct=-1,
            avg_memory_pct=-1,
            details=f"{size_gb}GB · Avg IOPS: {avg_iops_pct:.1f}% of provisioned",
        ))


def _list_resource_group_names(compute) -> list[str]:
    rgs = set()
    for vm in compute.virtual_machines.list_all():
        rgs.add(vm.id.split("/")[4])
    return list(rgs)


# ── AI analysis ───────────────────────────────────────────────

def get_ai_analysis(report: AuditReport) -> str:
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        return ""
    if not report.orphaned and not report.rightsizing:
        return "✅ No issues found. Subscription looks clean and well-sized."

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1",
    )

    orphaned_text = "\n".join([
        f"- [{r.resource_type}] {r.name}: ${r.monthly_cost_usd:.2f}/month — {r.details}"
        for r in report.orphaned
    ]) or "None found."

    rightsizing_text = "\n".join([
        f"- [{r.resource_type}] {r.name}: {r.current_sku} → {r.recommended_sku} "
        f"(saves ${r.monthly_saving_usd:.2f}/month · CPU: {r.avg_cpu_pct:.1f}%)"
        for r in report.rightsizing
    ]) or "None found."

    prompt = f"""You are a FinOps engineer reviewing an Azure subscription audit.

AUDIT DATE: {report.run_date}
ORPHANED RESOURCES SAVINGS: ${report.total_orphan_savings_usd:.2f}/month
RIGHT-SIZING SAVINGS: ${report.total_rightsizing_savings_usd:.2f}/month
TOTAL POTENTIAL SAVINGS: ${report.total_savings_usd:.2f}/month (${report.total_savings_usd * 12:.2f}/year)

ORPHANED RESOURCES:
{orphaned_text}

RIGHT-SIZING OPPORTUNITIES:
{rightsizing_text}

TASK:
1. Write a 2-sentence executive summary.
2. List top 3 quick wins — highest savings, lowest effort.
3. Flag anything needing investigation before acting (stopped VMs may be intentional, right-sizing needs load testing).
4. One sentence on annual savings impact.

Be direct and technical. Reader is a Senior DevOps engineer."""

    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            max_tokens=900,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI analysis unavailable: {e}"


# ── GitHub Issue formatter ────────────────────────────────────

def format_github_issue(report: AuditReport) -> tuple[str, str]:
    title = (
        f"🔍 Weekly Resource Audit — {report.run_date} — "
        f"${report.total_savings_usd:.2f}/month potential savings"
    )

    lines = [
        f"## 🔍 Azure Resource Audit — {report.run_date}",
        "",
        f"**Subscription:** `{report.subscription_id}`",
        f"**Orphaned resources:** {len(report.orphaned)} · "
        f"${report.total_orphan_savings_usd:.2f}/month",
        f"**Right-sizing opportunities:** {len(report.rightsizing)} · "
        f"${report.total_rightsizing_savings_usd:.2f}/month",
        f"**Total potential savings:** ${report.total_savings_usd:.2f}/month "
        f"(${report.total_savings_usd * 12:.2f}/year)",
        "",
    ]

    if report.ai_analysis:
        lines += [
            "## 🤖 AI Analysis (Groq · Llama 3.1)",
            "",
            report.ai_analysis,
            "",
            "---",
            "",
        ]

    # Orphaned resources table
    if report.orphaned:
        by_type: dict[str, list] = {}
        for r in report.orphaned:
            by_type.setdefault(r.resource_type, []).append(r)

        lines.append("## 🗑️ Orphaned Resources")
        lines.append("")
        for rtype, resources in by_type.items():
            total = sum(r.monthly_cost_usd for r in resources)
            lines += [
                f"### {rtype} ({len(resources)} · ${total:.2f}/month)",
                "",
                "| Name | Resource Group | Cost/month | Details | Action |",
                "|---|---|---|---|---|",
            ]
            for r in resources:
                lines.append(
                    f"| `{r.name}` | `{r.resource_group}` | "
                    f"${r.monthly_cost_usd:.2f} | {r.details} | {r.recommendation} |"
                )
            lines.append("")

    # Right-sizing table
    if report.rightsizing:
        lines += [
            "## 📐 Right-Sizing Recommendations",
            "",
            "| Resource | Name | Current SKU | Recommended SKU | "
            "Current Cost | Saving/month | Avg CPU | Details |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in report.rightsizing:
            cpu_str = f"{r.avg_cpu_pct:.1f}%" if r.avg_cpu_pct >= 0 else "N/A"
            lines.append(
                f"| {r.resource_type} | `{r.name}` | `{r.current_sku}` | "
                f"`{r.recommended_sku}` | ${r.current_cost_usd:.2f} | "
                f"**${r.monthly_saving_usd:.2f}** | {cpu_str} | {r.details} |"
            )
        lines += [
            "",
            "> ⚠️ **Before right-sizing:** validate during peak load. "
            "Metrics are 7-day averages — ensure no seasonal spikes.",
            "",
        ]

    if not report.orphaned and not report.rightsizing:
        lines += [
            "## ✅ No issues found",
            "",
            "Your Azure subscription is clean and well-sized. No action needed.",
            "",
        ]

    lines += [
        "---",
        "",
        f"_Generated automatically by [FinOps Intelligence Engine]"
        f"(https://github.com/vmprachi7/finops-intelligence-engine) "
        f"on {report.run_date}._",
        "",
        "_To run manually: Actions → Resource Audit → Run workflow_",
    ]

    return title, "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────

def main():
    subscription_id = os.environ["AZURE_SUBSCRIPTION_ID"]
    credential      = get_credential()

    compute_client   = ComputeManagementClient(credential, subscription_id)
    network_client   = NetworkManagementClient(credential, subscription_id)
    resource_client  = ResourceManagementClient(credential, subscription_id)
    monitor_client   = MonitorManagementClient(credential, subscription_id)
    aks_client       = ContainerServiceClient(credential, subscription_id)

    report = AuditReport(
        run_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        subscription_id=subscription_id,
    )

    print("🔍 Starting Azure resource audit...")
    print("")
    print("── Orphaned resources ──────────────────────────")

    print("  Checking unattached managed disks...")
    check_unattached_disks(compute_client, report)

    print("  Checking unassigned public IPs...")
    check_unassigned_public_ips(network_client, report)

    print("  Checking empty resource groups...")
    check_empty_resource_groups(resource_client, report)

    print("  Checking stopped VMs...")
    check_stopped_vms(compute_client, report)

    print("  Checking unused load balancers...")
    check_unused_load_balancers(network_client, report)

    print("")
    print("── Right-sizing (7-day avg metrics) ───────────")

    print("  Checking VM utilisation...")
    check_vm_rightsizing(compute_client, monitor_client, subscription_id, report)

    print("  Checking AKS node pool utilisation...")
    check_aks_rightsizing(aks_client, monitor_client, subscription_id, report)

    print("  Checking disk tier efficiency...")
    check_disk_rightsizing(compute_client, monitor_client, subscription_id, report)

    print("")
    print(f"✅ Audit complete")
    print(f"   Orphaned:     {len(report.orphaned)} resources · ${report.total_orphan_savings_usd:.2f}/month")
    print(f"   Right-sizing: {len(report.rightsizing)} resources · ${report.total_rightsizing_savings_usd:.2f}/month")
    print(f"   Total saving: ${report.total_savings_usd:.2f}/month (${report.total_savings_usd * 12:.2f}/year)")

    print("\n🤖 Getting AI analysis...")
    report.ai_analysis = get_ai_analysis(report)

    title, body = format_github_issue(report)

    with open("audit_report.json", "w") as f:
        json.dump({"title": title, "body": body}, f)

    print("✅ Report written to audit_report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
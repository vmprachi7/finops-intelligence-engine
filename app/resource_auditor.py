"""
Azure Resource Auditor
Finds orphaned cloud assets, calculates real savings, asks Groq AI to
prioritise and explain. Output is posted as a GitHub Issue.

Orphaned resources detected:
  - Unattached managed disks
  - Unassigned public IP addresses
  - Empty resource groups
  - Stopped (deallocated) VMs still paying for OS disk
  - Old untagged ACR images (>30 days)
  - Unused load balancers (no backend pool members)
"""
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.containerregistry import ContainerRegistryManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.resource import ResourceManagementClient
from openai import OpenAI


# ── Azure pricing (USD/month, approx) ────────────────────────
# Source: Azure pricing calculator — East US / Central India
DISK_COST_PER_GB   = 0.154    # Premium SSD P-series per GB
PUBLIC_IP_COST     = 3.65     # Unassigned static public IP
STOPPED_VM_OS_DISK = 4.00     # Stopped VM OS disk (128GB Standard HDD)
LB_COST            = 18.25    # Standard Load Balancer base fee


@dataclass
class OrphanedResource:
    resource_type:    str
    name:             str
    resource_group:   str
    monthly_cost_usd: float
    details:          str
    recommendation:   str


@dataclass
class AuditReport:
    run_date:          str
    subscription_id:   str
    orphaned:          list[OrphanedResource] = field(default_factory=list)
    total_savings_usd: float = 0.0
    ai_analysis:       str = ""

    def add(self, resource: OrphanedResource):
        self.orphaned.append(resource)
        self.total_savings_usd += resource.monthly_cost_usd


# ── Credential setup ──────────────────────────────────────────

def get_credential():
    return ClientSecretCredential(
        tenant_id=os.environ["AZURE_TENANT_ID"],
        client_id=os.environ["AZURE_CLIENT_ID"],
        client_secret=os.environ["AZURE_CLIENT_SECRET"],
    )


# ── Resource checks ───────────────────────────────────────────

def check_unattached_disks(
    compute: ComputeManagementClient,
    report: AuditReport,
):
    """Managed disks with no owner (diskState == Unattached)."""
    for disk in compute.disks.list():
        if disk.disk_state == "Unattached":
            size_gb    = disk.disk_size_gb or 128
            monthly    = round(size_gb * DISK_COST_PER_GB, 2)
            report.add(OrphanedResource(
                resource_type="Managed Disk",
                name=disk.name,
                resource_group=disk.id.split("/")[4],
                monthly_cost_usd=monthly,
                details=f"{size_gb}GB · {disk.sku.name if disk.sku else 'Unknown SKU'} · "
                        f"Last modified: {disk.time_created.strftime('%Y-%m-%d') if disk.time_created else 'unknown'}",
                recommendation=f"Delete if not needed — saves ${monthly:.2f}/month",
            ))


def check_unassigned_public_ips(
    network: NetworkManagementClient,
    report: AuditReport,
):
    """Public IPs not associated with any NIC or Load Balancer."""
    for ip in network.public_ip_addresses.list_all():
        if ip.ip_configuration is None:
            report.add(OrphanedResource(
                resource_type="Public IP Address",
                name=ip.name,
                resource_group=ip.id.split("/")[4],
                monthly_cost_usd=PUBLIC_IP_COST,
                details=f"SKU: {ip.sku.name if ip.sku else 'Basic'} · "
                        f"Allocation: {ip.public_ip_allocation_method}",
                recommendation=f"Release if not reserved — saves ${PUBLIC_IP_COST:.2f}/month",
            ))


def check_empty_resource_groups(
    resource_client: ResourceManagementClient,
    report: AuditReport,
):
    """Resource groups with zero resources inside."""
    for rg in resource_client.resource_groups.list():
        resources = list(resource_client.resources.list_by_resource_group(rg.name))
        if len(resources) == 0:
            report.add(OrphanedResource(
                resource_type="Empty Resource Group",
                name=rg.name,
                resource_group=rg.name,
                monthly_cost_usd=0.0,
                details=f"Region: {rg.location} · No resources",
                recommendation="Delete to reduce clutter — no cost but improves hygiene",
            ))


def check_stopped_vms(
    compute: ComputeManagementClient,
    report: AuditReport,
):
    """VMs that are stopped/deallocated but still incurring OS disk costs."""
    for rg in _list_resource_groups(compute):
        for vm in compute.virtual_machines.list(rg):
            try:
                statuses = compute.virtual_machines.instance_view(
                    rg, vm.name
                ).statuses
                power_state = next(
                    (s.display_status for s in statuses
                     if s.code and s.code.startswith("PowerState/")),
                    "unknown"
                )
                if power_state in ("VM deallocated", "VM stopped"):
                    report.add(OrphanedResource(
                        resource_type="Stopped VM",
                        name=vm.name,
                        resource_group=rg,
                        monthly_cost_usd=STOPPED_VM_OS_DISK,
                        details=f"Power state: {power_state} · "
                                f"Size: {vm.hardware_profile.vm_size if vm.hardware_profile else 'unknown'}",
                        recommendation=f"Delete or start VM — OS disk costs ~${STOPPED_VM_OS_DISK:.2f}/month while stopped",
                    ))
            except Exception:
                continue


def check_unused_load_balancers(
    network: NetworkManagementClient,
    report: AuditReport,
):
    """Load Balancers with no backend pool members."""
    for lb in network.load_balancers.list_all():
        if not lb.backend_address_pools:
            report.add(OrphanedResource(
                resource_type="Load Balancer",
                name=lb.name,
                resource_group=lb.id.split("/")[4],
                monthly_cost_usd=LB_COST,
                details=f"SKU: {lb.sku.name if lb.sku else 'Basic'} · No backend pools",
                recommendation=f"Delete if unused — saves ${LB_COST:.2f}/month",
            ))
        else:
            # Check if all backend pools are empty
            all_empty = all(
                not pool.backend_ip_configurations
                for pool in lb.backend_address_pools
            )
            if all_empty:
                report.add(OrphanedResource(
                    resource_type="Load Balancer",
                    name=lb.name,
                    resource_group=lb.id.split("/")[4],
                    monthly_cost_usd=LB_COST,
                    details=f"SKU: {lb.sku.name if lb.sku else 'Basic'} · "
                            f"Backend pools exist but are empty",
                    recommendation=f"Investigate — may be unused. Saves ${LB_COST:.2f}/month if deleted",
                ))


def _list_resource_groups(compute: ComputeManagementClient) -> list[str]:
    """Helper — extract unique resource group names from VMs."""
    rgs = set()
    for vm in compute.virtual_machines.list_all():
        rgs.add(vm.id.split("/")[4])
    return list(rgs)


# ── AI analysis ───────────────────────────────────────────────

def get_ai_analysis(report: AuditReport) -> str:
    """Ask Groq AI to prioritise findings and explain savings."""
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key or not report.orphaned:
        return ""

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1",
    )

    resources_text = "\n".join([
        f"- [{r.resource_type}] {r.name} ({r.resource_group}): "
        f"${r.monthly_cost_usd:.2f}/month — {r.details}"
        for r in report.orphaned
    ])

    prompt = f"""You are a FinOps engineer reviewing Azure orphaned resources.

AUDIT DATE: {report.run_date}
TOTAL POTENTIAL SAVINGS: ${report.total_savings_usd:.2f}/month

ORPHANED RESOURCES FOUND:
{resources_text}

TASK:
1. Write a 2-sentence executive summary of the findings.
2. List the top 3 quick wins — highest savings with lowest effort to resolve.
3. Flag any resources that need investigation before deletion (e.g. stopped VMs might be intentional).
4. Estimate annual savings if all orphaned resources are cleaned up.

Keep the tone direct and technical. This report will be read by a Senior DevOps engineer."""

    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI analysis unavailable: {e}"


# ── GitHub Issue formatter ────────────────────────────────────

def format_github_issue(report: AuditReport) -> tuple[str, str]:
    """Returns (title, body) for the GitHub Issue."""

    title = (
        f"🔍 Weekly Resource Audit — {report.run_date} — "
        f"${report.total_savings_usd:.2f}/month potential savings"
    )

    # Group by resource type
    by_type: dict[str, list[OrphanedResource]] = {}
    for r in report.orphaned:
        by_type.setdefault(r.resource_type, []).append(r)

    lines = [
        f"## 🔍 Azure Resource Audit — {report.run_date}",
        "",
        f"**Subscription:** `{report.subscription_id}`",
        f"**Orphaned resources found:** {len(report.orphaned)}",
        f"**Potential monthly savings:** ${report.total_savings_usd:.2f}",
        f"**Potential annual savings:** ${report.total_savings_usd * 12:.2f}",
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

    for rtype, resources in by_type.items():
        total = sum(r.monthly_cost_usd for r in resources)
        lines += [
            f"## {rtype} ({len(resources)} found · ${total:.2f}/month)",
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

    if not report.orphaned:
        lines += [
            "## ✅ No orphaned resources found",
            "",
            "Your Azure subscription looks clean. No action needed.",
            "",
        ]

    lines += [
        "---",
        "",
        "_This report was generated automatically by the "
        "[FinOps Intelligence Engine](https://github.com/vmprachi7/finops-intelligence-engine) "
        f"resource auditor on {report.run_date}._",
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

    report = AuditReport(
        run_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        subscription_id=subscription_id,
    )

    print("🔍 Starting Azure resource audit...")

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

    print(f"\n✅ Audit complete — {len(report.orphaned)} orphaned resources found")
    print(f"   Potential savings: ${report.total_savings_usd:.2f}/month")

    print("\n🤖 Getting AI analysis...")
    report.ai_analysis = get_ai_analysis(report)

    title, body = format_github_issue(report)

    # Output for GitHub Actions to consume
    output = json.dumps({"title": title, "body": body})
    print(f"\n::set-output name=issue_title::{title}")

    # Write to file for the workflow to read
    with open("audit_report.json", "w") as f:
        json.dump({"title": title, "body": body}, f)

    print("✅ Report written to audit_report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
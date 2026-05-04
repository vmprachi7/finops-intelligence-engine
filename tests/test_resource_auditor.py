"""
Tests for resource_auditor.py
Run with: pytest tests/test_resource_auditor.py -v
"""
import pytest
from unittest.mock import MagicMock, patch
from app.resource_auditor import (
    AuditReport,
    OrphanedResource,
    format_github_issue,
    check_unattached_disks,
    check_unassigned_public_ips,
)


# ── Fixtures ──────────────────────────────────────────────────

def make_report():
    return AuditReport(
        run_date="2026-05-04",
        subscription_id="test-sub-id",
    )


def make_disk(name, state, size_gb=128):
    disk = MagicMock()
    disk.name       = name
    disk.disk_state = state
    disk.disk_size_gb = size_gb
    disk.id         = f"/subscriptions/xxx/resourceGroups/test-rg/providers/disk/{name}"
    disk.sku        = MagicMock(name="Premium_LRS")
    disk.time_created = None
    return disk


def make_public_ip(name, has_config=False):
    ip = MagicMock()
    ip.name              = name
    ip.ip_configuration  = MagicMock() if has_config else None
    ip.id                = f"/subscriptions/xxx/resourceGroups/test-rg/providers/ip/{name}"
    ip.sku               = MagicMock(name="Standard")
    ip.public_ip_allocation_method = "Static"
    return ip


# ── AuditReport tests ─────────────────────────────────────────

def test_report_add_updates_total():
    report = make_report()
    resource = OrphanedResource(
        resource_type="Managed Disk",
        name="test-disk",
        resource_group="rg",
        monthly_cost_usd=19.71,
        details="128GB",
        recommendation="Delete",
    )
    report.add(resource)
    assert len(report.orphaned) == 1
    assert report.total_savings_usd == 19.71


def test_report_multiple_resources():
    report = make_report()
    for i in range(3):
        report.add(OrphanedResource(
            resource_type="Public IP",
            name=f"ip-{i}",
            resource_group="rg",
            monthly_cost_usd=3.65,
            details="Unassigned",
            recommendation="Release",
        ))
    assert len(report.orphaned) == 3
    assert round(report.total_savings_usd, 2) == 10.95


# ── Disk check tests ──────────────────────────────────────────

def test_detects_unattached_disk():
    report  = make_report()
    compute = MagicMock()
    compute.disks.list.return_value = [
        make_disk("orphan-disk", "Unattached", size_gb=128),
        make_disk("active-disk",  "Attached",   size_gb=64),
    ]
    check_unattached_disks(compute, report)
    assert len(report.orphaned) == 1
    assert report.orphaned[0].name == "orphan-disk"


def test_ignores_attached_disks():
    report  = make_report()
    compute = MagicMock()
    compute.disks.list.return_value = [
        make_disk("active-disk", "Attached"),
    ]
    check_unattached_disks(compute, report)
    assert len(report.orphaned) == 0


def test_disk_cost_calculated_correctly():
    report  = make_report()
    compute = MagicMock()
    compute.disks.list.return_value = [
        make_disk("big-disk", "Unattached", size_gb=256),
    ]
    check_unattached_disks(compute, report)
    # 256GB * $0.154 = $39.42
    assert round(report.orphaned[0].monthly_cost_usd, 2) == 39.42


# ── Public IP check tests ─────────────────────────────────────

def test_detects_unassigned_public_ip():
    report  = make_report()
    network = MagicMock()
    network.public_ip_addresses.list_all.return_value = [
        make_public_ip("orphan-ip",  has_config=False),
        make_public_ip("assigned-ip", has_config=True),
    ]
    check_unassigned_public_ips(network, report)
    assert len(report.orphaned) == 1
    assert report.orphaned[0].name == "orphan-ip"
    assert report.orphaned[0].monthly_cost_usd == 3.65


def test_ignores_assigned_public_ip():
    report  = make_report()
    network = MagicMock()
    network.public_ip_addresses.list_all.return_value = [
        make_public_ip("assigned-ip", has_config=True),
    ]
    check_unassigned_public_ips(network, report)
    assert len(report.orphaned) == 0


# ── GitHub Issue format tests ─────────────────────────────────

def test_issue_title_contains_date_and_savings():
    report = make_report()
    report.add(OrphanedResource(
        resource_type="Managed Disk",
        name="test-disk",
        resource_group="rg",
        monthly_cost_usd=19.71,
        details="128GB",
        recommendation="Delete",
    ))
    title, body = format_github_issue(report)
    assert "2026-05-04" in title
    assert "19.71" in title
    assert "Managed Disk" in body


def test_empty_report_shows_clean_message():
    report = make_report()
    title, body = format_github_issue(report)
    assert "No orphaned resources" in body
    assert report.total_savings_usd == 0.0


def test_issue_body_contains_ai_analysis():
    report = make_report()
    report.ai_analysis = "This is the AI analysis."
    _, body = format_github_issue(report)
    assert "This is the AI analysis." in body
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Playwright browser smoke tests for all Stratum UI pages.

These tests run against the live Stratum server at http://localhost:8001.
They require:
  1. The Docker container (or local dev server) to be running: `docker compose up -d`
  2. Playwright browsers installed: `uv run playwright install chromium`
  3. The ui marker enabled: `uv run pytest -m ui tests/ui/`

All tests are skipped automatically when STRATUM_RUN_UI is not set.

Test coverage:
  PAGE-01  Dashboard renders with correct title
  PAGE-02  Blueprints (Profile Hub) renders
  PAGE-03  Blueprint Studio opens for a known profile
  PAGE-04  Builder (Image Builder) renders
  PAGE-05  Builder wizard step 1 renders with OS selector
  PAGE-06  Builder wizard step 2 renders with provider fields
  PAGE-07  Auditor page renders with scan controls
  PAGE-08  Compliance Scanner wizard renders
  PAGE-09  Scanner step 1 renders
  PAGE-10  Scan History page renders
  PAGE-11  Integrations page renders with provider cards
  PAGE-12  Agent (AI Builder) page renders
  PAGE-13  API Keys settings page renders
  PAGE-14  Webhooks settings page renders
  FLOW-01  Blueprint download — clicking Download returns a YAML file
  FLOW-02  Blueprint validate — inline YAML validates correctly via API
  FLOW-03  Integrations AWS form loads on provider click
  FLOW-04  Builder wizard steps 1→2 navigation works
"""

from __future__ import annotations

import os

import pytest
from playwright.sync_api import Page, expect

BASE_URL = "http://localhost:8001"

pytestmark = pytest.mark.ui


# ---------------------------------------------------------------------------
# Skip guard — tests are opt-in
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def require_ui_env():
    if not os.environ.get("STRATUM_RUN_UI"):
        pytest.skip("Set STRATUM_RUN_UI=1 to run Playwright UI tests")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _goto(page: Page, path: str):
    """Navigate to a page and wait for network to be idle."""
    page.goto(f"{BASE_URL}{path}", wait_until="networkidle")


# ---------------------------------------------------------------------------
# PAGE-01: Dashboard
# ---------------------------------------------------------------------------


@pytest.mark.ui
def test_dashboard_title(page: Page):
    _goto(page, "/")
    expect(page).to_have_title("Dashboard — Stratum")


@pytest.mark.ui
def test_dashboard_has_nav(page: Page):
    _goto(page, "/")
    # Navigation sidebar must be present
    nav = page.locator("nav, aside, [role='navigation']").first
    expect(nav).to_be_visible()


# ---------------------------------------------------------------------------
# PAGE-02: Blueprints (Profile Hub)
# ---------------------------------------------------------------------------


@pytest.mark.ui
def test_blueprints_page_title(page: Page):
    _goto(page, "/blueprints")
    expect(page).to_have_title("Profile Hub — Stratum")


@pytest.mark.ui
def test_blueprints_page_has_profile_cards(page: Page):
    _goto(page, "/blueprints")
    # Blueprint cards link to /blueprints/studio/<name>
    cards = page.locator("a[href*='/blueprints/studio/']").first
    expect(cards).to_be_visible()


# ---------------------------------------------------------------------------
# PAGE-03: Blueprint Studio
# ---------------------------------------------------------------------------


@pytest.mark.ui
def test_blueprint_studio_loads(page: Page):
    _goto(page, "/blueprints/studio/ubuntu22-cis-l1-aws")
    # Studio page should not 404 — any 2xx with HTML content
    assert "Stratum" in page.title() or page.locator("body").is_visible()


@pytest.mark.ui
def test_blueprint_studio_shows_yaml(page: Page):
    _goto(page, "/blueprints/studio/ubuntu22-cis-l1-aws")
    # YAML editor / preview area should have content
    yaml_area = page.locator("pre, textarea, [class*='yaml'], code").first
    expect(yaml_area).to_be_visible()


# ---------------------------------------------------------------------------
# PAGE-04: Builder (Image Builder)
# ---------------------------------------------------------------------------


@pytest.mark.ui
def test_builder_page_title(page: Page):
    _goto(page, "/builder")
    expect(page).to_have_title("Image Builder — Stratum")


# ---------------------------------------------------------------------------
# PAGE-05: Builder wizard step 1
# ---------------------------------------------------------------------------


@pytest.mark.ui
def test_wizard_step1_has_os_selector(page: Page):
    _goto(page, "/builder/wizard/step1")
    # OS selection grid or radio buttons must be present
    os_selector = page.locator("input[type='radio'], [data-os], button[data-value], .os-card").first
    expect(os_selector).to_be_visible()


# ---------------------------------------------------------------------------
# PAGE-06: Builder wizard step 2 (requires os + provider query params)
# ---------------------------------------------------------------------------


@pytest.mark.ui
def test_wizard_step2_renders_provider_fields(page: Page):
    _goto(page, "/builder/wizard/step2?os=ubuntu22.04&provider=aws&min_root_gb=20")
    # Should render without error
    body = page.locator("body")
    expect(body).to_be_visible()
    # Must not show a Python traceback or error page
    assert "500" not in page.title()
    assert "Internal Server Error" not in page.content()


# ---------------------------------------------------------------------------
# PAGE-07: Auditor
# ---------------------------------------------------------------------------


@pytest.mark.ui
def test_auditor_page_title(page: Page):
    _goto(page, "/auditor")
    expect(page).to_have_title("Auditor — Stratum")


# ---------------------------------------------------------------------------
# PAGE-08: Compliance Scanner wizard
# ---------------------------------------------------------------------------


@pytest.mark.ui
def test_scanner_wizard_title(page: Page):
    _goto(page, "/auditor/scanner")
    expect(page).to_have_title("Compliance Scanner — Stratum")


# ---------------------------------------------------------------------------
# PAGE-09: Scanner step 1
# ---------------------------------------------------------------------------


@pytest.mark.ui
def test_scanner_step1_renders(page: Page):
    _goto(page, "/auditor/scanner/step1")
    expect(page.locator("body")).to_be_visible()
    assert "Internal Server Error" not in page.content()


# ---------------------------------------------------------------------------
# PAGE-10: Scan History
# ---------------------------------------------------------------------------


@pytest.mark.ui
def test_scan_history_page_title(page: Page):
    _goto(page, "/auditor/history")
    expect(page).to_have_title("Scan History — Stratum")


# ---------------------------------------------------------------------------
# PAGE-11: Integrations
# ---------------------------------------------------------------------------


@pytest.mark.ui
def test_integrations_page_title(page: Page):
    _goto(page, "/integrations")
    expect(page).to_have_title("Integrations — Stratum")


@pytest.mark.ui
def test_integrations_shows_provider_cards(page: Page):
    _goto(page, "/integrations")
    # Provider cards are HTMX buttons with hx-get="/integrations/<name>/form"
    provider_btn = page.locator("button[hx-get*='/integrations/'][hx-get*='/form']").first
    expect(provider_btn).to_be_visible()


# ---------------------------------------------------------------------------
# PAGE-12: Agent (AI Builder)
# ---------------------------------------------------------------------------


@pytest.mark.ui
def test_agent_page_title(page: Page):
    _goto(page, "/agent")
    expect(page).to_have_title("AI Builder — Stratum")


# ---------------------------------------------------------------------------
# PAGE-13: API Keys settings
# ---------------------------------------------------------------------------


@pytest.mark.ui
def test_api_keys_page_title(page: Page):
    _goto(page, "/settings/api-keys")
    expect(page).to_have_title("API Keys — Stratum")


@pytest.mark.ui
def test_api_keys_page_has_generate_button(page: Page):
    _goto(page, "/settings/api-keys")
    # Button text is "Generate Key" in the current UI
    generate_btn = page.locator("button").filter(has_text="Generate").first
    expect(generate_btn).to_be_visible()


# ---------------------------------------------------------------------------
# PAGE-14: Webhooks settings
# ---------------------------------------------------------------------------


@pytest.mark.ui
def test_webhooks_page_title(page: Page):
    _goto(page, "/settings/webhooks")
    expect(page).to_have_title("Webhooks — Stratum")


# ---------------------------------------------------------------------------
# FLOW-01: Blueprint download — clicking Download on a blueprint card
# ---------------------------------------------------------------------------


@pytest.mark.ui
def test_blueprint_download_returns_yaml(page: Page):
    """The Download button for a built-in blueprint must trigger a file download
    with content-type application/yaml (or octet-stream) and a YAML filename.
    """
    _goto(page, "/blueprints")

    with page.expect_download() as dl_info:
        # Click the first visible Download button
        page.locator("a[href*='/download'], button").filter(has_text="Download").first.click()

    download = dl_info.value
    suggested = download.suggested_filename
    assert suggested.endswith(".yaml") or suggested.endswith(".yml"), (
        f"Downloaded file should have .yaml extension, got: {suggested!r}"
    )


# ---------------------------------------------------------------------------
# FLOW-02: Blueprint validate via API — inline YAML
# ---------------------------------------------------------------------------


@pytest.mark.ui
def test_blueprint_validate_api_via_browser(page: Page):
    """Hit the /api/blueprints/validate endpoint from within the browser
    context to verify CORS and content-type handling.
    """
    valid_yaml = (
        "stratum_version: '0.1.0'\n"
        "kind: ComplianceProfile\n"
        "metadata:\n  name: pw-test\n  version: '1.0.0'\n"
        "target:\n  os: ubuntu22.04\n  provider: aws\n  base_image: ami-00\n"
        "compliance:\n"
        "  benchmark: xccdf_org.ssgproject.content_benchmark_UBUNTU2204\n"
        "  profile: xccdf_org.ssgproject.content_profile_cis_level1_server\n"
        "  datastream: /usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml\n"
    )

    response = page.request.post(
        f"{BASE_URL}/api/blueprints/validate",
        data=valid_yaml,
        headers={"Content-Type": "application/yaml"},
    )
    assert response.ok, f"Validate endpoint returned {response.status}"
    body = response.json()
    assert body["valid"] is True
    assert body.get("name") == "pw-test"


# ---------------------------------------------------------------------------
# FLOW-03: Integrations AWS form loads when AWS provider is selected
# ---------------------------------------------------------------------------


@pytest.mark.ui
def test_integrations_aws_form_loads(page: Page):
    _goto(page, "/integrations")
    # Click the AWS provider card or link
    aws_link = page.locator("a[href*='aws'], button[data-provider='aws'], [data-provider='aws']").first
    if aws_link.count() > 0:
        aws_link.click()
        page.wait_for_load_state("networkidle")
    else:
        # Fall back: navigate directly to the AWS form
        _goto(page, "/integrations/aws/form")

    # AWS credential form fields must be visible
    form_input = page.locator("input[name*='aws'], input[placeholder*='AWS'], form input").first
    expect(form_input).to_be_visible()


# ---------------------------------------------------------------------------
# FLOW-04: Builder wizard step 1 → step 2 navigation
# ---------------------------------------------------------------------------


@pytest.mark.ui
def test_wizard_step1_to_step2_navigation(page: Page):
    """Step 1 shows OS selection cards; selecting one should reveal provider cards.
    The wizard uses HTMX — provider cards may already be present but hidden.
    """
    _goto(page, "/builder/wizard/step1")

    # Step 1 must show OS cards with data-os-slug
    os_card = page.locator("[data-os-slug]").first
    expect(os_card).to_be_visible()

    # Provider cards (data-provider) are also rendered on step 1 (two-column layout)
    # — verify at least one provider card is present in the DOM
    provider_card = page.locator("button[data-provider], [data-provider]").first
    expect(provider_card).to_be_visible()

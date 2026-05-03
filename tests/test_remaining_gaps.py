# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Tests covering remaining coverage gaps across multiple modules.

Targets:
  core/report.py         43, 64, 150, 162, 377  — _score_to_grade(None), _risk_score(None),
                                                   trend/pct_change None-score paths,
                                                   register_formatter bad type
  openscap/parser.py     45, 74                 — parse_arf no TestResult, _find_test_result fallback
  plugins/registry.py    49-50                  — registry.all() returns dict copy
  core/agent.py          158-159, 285-286,       — _enrich_blueprint validation fail,
                         393, 397               — _retry_build_yaml fallback,
                                                   _execute_tool enrich/analyze dispatch
  core/agent.py          494-498, 540           — run_build_agent agent_turn exception,
                                                   on_token call before tool dispatch
  core/auditor.py        214-215                — run_image_scan exception logging
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ===========================================================================
# core/report.py
# ===========================================================================


class TestReportGaps:
    def test_score_to_grade_none_returns_f(self):
        """_score_to_grade(None) returns 'F'."""
        from stratum.core.report import _score_to_grade

        assert _score_to_grade(None) == "F"

    def test_risk_score_none_returns_100(self):
        """_risk_score(None) returns 100.0 (maximum risk)."""
        from stratum.core.report import _risk_score

        assert _risk_score(None) == 100.0

    def test_delta_report_none_scores_trend_stable(self):
        """generate_delta_report with None scores produces trend='stable', pct_change=0."""
        from pathlib import Path

        from stratum.core.report import generate_delta_report

        none_scan = {"score": None, "rules": []}
        with patch("stratum.core.report.parse_arf", return_value=none_scan):
            result = generate_delta_report(Path("/fake/a.xml"), Path("/fake/b.xml"))
        assert result["trend"] == "stable"
        assert result["pct_change"] == 0.0

    def test_delta_report_zero_baseline_score_pct_change_zero(self):
        """generate_delta_report with baseline score=0 does not divide by zero."""
        from pathlib import Path

        from stratum.core.report import generate_delta_report

        call_count = {"n": 0}

        def _fake_parse(path):
            call_count["n"] += 1
            return {"score": 0.0 if call_count["n"] == 1 else 50.0, "rules": []}

        with patch("stratum.core.report.parse_arf", side_effect=_fake_parse):
            result = generate_delta_report(Path("/fake/a.xml"), Path("/fake/b.xml"))
        assert result["pct_change"] == 0.0

    def test_register_formatter_non_subclass_raises_type_error(self):
        """register_formatter raises TypeError for non-ReportFormatter subclass."""
        from stratum.core.report import register_formatter

        with pytest.raises(TypeError, match="must be a subclass of ReportFormatter"):
            register_formatter("badformat", str)

    def test_generate_summary_with_mocked_parse_arf(self):
        """generate_summary returns a dict with score, grade, and findings."""
        from pathlib import Path

        from stratum.core.report import generate_summary

        fake_data = {
            "score": 70.0,
            "benchmark_id": "bench-1",
            "profile_id": "profile-1",
            "start_time": "2026-01-01T00:00:00",
            "end_time": "2026-01-01T00:05:00",
            "counts": {"pass": 8, "fail": 2},
            "rules": [
                {"id": "rule_1", "result": "fail", "severity": "high"},
                {"id": "rule_2", "result": "pass", "severity": "medium"},
            ],
        }
        with patch("stratum.core.report.parse_arf", return_value=fake_data):
            result = generate_summary(Path("/fake/result.xml"))
        assert result["score"] == 70.0
        assert result["grade"] in ("A", "B", "C", "D", "F")


# ===========================================================================
# openscap/parser.py
# ===========================================================================


class TestOpenSCAPParserGaps:
    def _write_xccdf(self, tmp_path: Path, content: str) -> Path:
        p = tmp_path / "result.xml"
        p.write_text(content)
        return p

    def test_parse_arf_no_test_result_raises(self, tmp_path):
        """parse_arf raises ValueError when no TestResult element is found."""
        from stratum.openscap.parser import parse_arf

        xml_no_result = textwrap.dedent("""\
            <?xml version="1.0"?>
            <arf:asset-report-collection xmlns:arf="http://scap.nist.gov/schema/asset-reporting-format/1.1"
                                         xmlns:xccdf="http://checklists.nist.gov/xccdf/1.2">
            </arf:asset-report-collection>
        """)
        p = self._write_xccdf(tmp_path, xml_no_result)
        with pytest.raises(ValueError, match="No xccdf:TestResult"):
            parse_arf(p)

    def test_find_test_result_fallback_to_xccdf_root(self, tmp_path):
        """_find_test_result returns TestResult when root IS the XCCDF benchmark."""
        from stratum.openscap.parser import parse_arf

        xccdf_xml = textwrap.dedent("""\
            <?xml version="1.0"?>
            <xccdf:Benchmark xmlns:xccdf="http://checklists.nist.gov/xccdf/1.2">
              <xccdf:TestResult id="r1">
                <xccdf:score>85.0</xccdf:score>
              </xccdf:TestResult>
            </xccdf:Benchmark>
        """)
        p = self._write_xccdf(tmp_path, xccdf_xml)
        result = parse_arf(p)
        assert result["score"] == 85.0


# ===========================================================================
# plugins/registry.py
# ===========================================================================


class TestPluginsRegistry:
    def test_registry_all_returns_dict_copy(self):
        """registry.all() returns a dict copy of registered providers."""
        from stratum.plugins.base_provider import BaseProvider, ProviderResult
        from stratum.plugins.registry import ProviderRegistry

        class TmpProvider(BaseProvider):
            name = "tmp_all_test"

            def provision(self, profile, **kwargs):
                return "i"

            def run_ansible(self, instance_id, profile):
                pass

            def snapshot(self, instance_id, profile):
                return ProviderResult(artifact_id="a", artifact_type="ami")

            def teardown(self, instance_id):
                pass

        reg = ProviderRegistry()
        # Register directly for test isolation
        with reg._lock:
            reg._providers["tmp_all_test"] = TmpProvider

        all_providers = reg.all()
        assert "tmp_all_test" in all_providers
        assert isinstance(all_providers, dict)
        # Verify it's a copy — mutations don't affect registry
        del all_providers["tmp_all_test"]
        assert "tmp_all_test" in reg._providers


# ===========================================================================
# core/agent.py — _enrich_blueprint validation failure
# ===========================================================================


class TestAgentCoreGaps:
    _VALID_YAML = """\
stratum_version: "0.1.0"
kind: ComplianceProfile
metadata:
  name: gap-agent-profile
  version: "1.0.0"
target:
  os: ubuntu22.04
  provider: aws
  base_image: ami-00000000
compliance:
  benchmark: xccdf_org.ssgproject.content_benchmark_UBUNTU2204
  profile: xccdf_org.ssgproject.content_profile_cis_level1_server
  datastream: /usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml
"""

    def test_enrich_blueprint_validation_failure_returns_error(self):
        """_enrich_blueprint returns error when enriched YAML fails Pydantic validation."""
        from stratum.core.agent import _enrich_blueprint

        # Minimal YAML that parses fine but fails ComplianceProfile.model_validate
        bad_yaml = "stratum_version: '0.1.0'\nkind: ComplianceProfile\nmetadata:\n  name: bad\n"
        result = _enrich_blueprint(bad_yaml, provider="aws")
        assert "error" in result

    def test_retry_build_yaml_invalid_yaml_returns_fallback(self):
        """_retry_build_yaml returns original yaml when modifications can't be applied."""
        from stratum.core.agent import _retry_build_yaml

        result = _retry_build_yaml(self._VALID_YAML, "{{invalid yaml{{{{")
        # Should return the original yaml with a 'applied' message about failure
        assert "updated_yaml" in result
        assert result["updated_yaml"] == self._VALID_YAML

    def test_retry_build_yaml_valid_but_invalid_schema_returns_fallback(self):
        """_retry_build_yaml falls back when YAML parses but fails schema validation."""
        from stratum.core.agent import _retry_build_yaml

        # Valid YAML dict but missing required fields → model_validate fails → fallback
        modifications = "just_a_string_not_a_dict: true"
        result = _retry_build_yaml(self._VALID_YAML, modifications)
        assert "updated_yaml" in result

    @pytest.mark.anyio
    async def test_execute_tool_start_build(self):
        """_execute_tool dispatches 'start_build' to _start_build (line 393)."""
        from stratum.core.agent import _execute_tool

        def _close_coro(coro, *a, **kw):
            if hasattr(coro, "close"):
                coro.close()
            return MagicMock()

        with patch("stratum.core.builder.run_build", new_callable=AsyncMock):
            with patch("asyncio.create_task", side_effect=_close_coro):
                result = await _execute_tool(
                    "start_build",
                    {
                        "yaml_text": self._VALID_YAML,
                        "provider": "aws",
                    },
                )
        assert "job_id" in result or "error" in result

    @pytest.mark.anyio
    async def test_execute_tool_get_scan_report(self):
        """_execute_tool dispatches 'get_scan_report' to _get_scan_report (line 397)."""
        from stratum.core.agent import _execute_tool

        with patch("stratum.core.builder.get_job", return_value=None):
            result = await _execute_tool("get_scan_report", {"job_id": "nonexistent-000"})
        assert "error" in result

    @pytest.mark.anyio
    async def test_execute_tool_enrich_blueprint(self):
        """_execute_tool dispatches 'enrich_blueprint' to _enrich_blueprint."""
        from stratum.core.agent import _execute_tool

        result = await _execute_tool(
            "enrich_blueprint",
            {
                "yaml_text": self._VALID_YAML,
                "provider": "aws",
            },
        )
        assert isinstance(result, dict)
        assert "enriched_yaml" in result or "error" in result

    @pytest.mark.anyio
    async def test_execute_tool_analyze_findings(self):
        """_execute_tool dispatches 'analyze_findings' to _analyze_findings."""
        import json

        from stratum.core.agent import _execute_tool

        findings = [{"id": "sshd_rule", "title": "SSH root login", "severity": "high"}]
        result = await _execute_tool(
            "analyze_findings",
            {
                "findings_json": json.dumps(findings),
            },
        )
        assert isinstance(result, dict)
        assert "summary" in result or "error" in result

    @pytest.mark.anyio
    async def test_run_build_agent_agent_turn_exception_returns_result_with_error(self):
        """When agent_turn raises, run_build_agent catches it and returns result.error."""
        from stratum.core.agent import run_build_agent
        from stratum.core.llm.base import LLMBackend

        class FailingBackend(LLMBackend):
            async def agent_turn(self, messages, tools, system, max_tokens, on_token):
                raise RuntimeError("LLM quota exceeded")

        tokens = []

        async def on_token(t):
            tokens.append(t)

        with patch("stratum.core.llm.get_backend", return_value=FailingBackend()):
            result = await run_build_agent(
                blueprint_yaml=self._VALID_YAML,
                provider="aws",
                on_token=on_token,
            )

        assert result.error is not None
        assert "LLM quota exceeded" in result.error
        # on_token should have received the error text
        assert any("ERROR" in t or "quota" in t for t in tokens)

    @pytest.mark.anyio
    async def test_run_build_agent_tool_call_emits_on_token(self):
        """Tool calls in run_build_agent emit a '*[Calling ...]* token via on_token."""
        from stratum.core.agent import run_build_agent
        from stratum.core.llm.base import AgentTurnResult, TextBlock, ToolUseBlock

        # Turn 1: tool_use → validate_blueprint
        # Turn 2: end_turn with artifact/grade in text
        call_count = {"n": 0}

        class MockBackend:
            async def agent_turn(self, messages, tools, system, max_tokens, on_token):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    return AgentTurnResult(
                        stop_reason="tool_use",
                        content=[
                            # TextBlock is not a ToolUseBlock → hits line 540 (continue)
                            TextBlock(text="Thinking about it..."),
                            ToolUseBlock(
                                id="tu-gap-001",
                                name="validate_blueprint",
                                input={"blueprint_yaml": self._VALID_YAML},
                            ),
                        ],
                    )
                # Second turn: end_turn
                await on_token("Build done.\nArtifact: ami-gap-001\nGrade: A")
                return AgentTurnResult(
                    stop_reason="end_turn",
                    content=[TextBlock(text="Build done.\nArtifact: ami-gap-001\nGrade: A")],
                )

        # Bind _VALID_YAML to the nested class
        _yaml = self._VALID_YAML
        MockBackend._VALID_YAML = _yaml

        tokens = []

        async def on_token(t):
            tokens.append(t)

        with patch("stratum.core.llm.get_backend", return_value=MockBackend()):
            await run_build_agent(
                blueprint_yaml=_yaml,
                provider="aws",
                on_token=on_token,
            )

        # Line 540: on_token called with "[Calling validate_blueprint...]"
        assert any("Calling validate_blueprint" in t for t in tokens)


# ===========================================================================
# core/auditor.py — run_audit webhook except path (lines 214-215)
# ===========================================================================


class TestAuditorWebhookExcept:
    @pytest.mark.anyio
    async def test_run_audit_webhook_create_task_raises(self):
        """run_audit swallows exception when asyncio.create_task raises (lines 214-215)."""

        from stratum.core.auditor import AuditStatus, run_audit
        from stratum.core.blueprint import ComplianceProfile

        profile = ComplianceProfile.model_validate(
            {
                "stratum_version": "0.1.0",
                "kind": "ComplianceProfile",
                "metadata": {"name": "webhook-exc-test", "version": "1.0.0"},
                "target": {"os": "ubuntu22.04", "provider": "aws", "base_image": "ami-00"},
                "compliance": {
                    "benchmark": "xccdf_org.ssgproject.content_benchmark_UBUNTU2204",
                    "profile": "xccdf_org.ssgproject.content_profile_cis_level1_server",
                    "datastream": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml",
                },
            }
        )

        def _close_and_raise(coro, *a, **kw):
            if hasattr(coro, "close"):
                coro.close()
            raise RuntimeError("no loop")

        with patch("stratum.core.auditor._persist_jobs"):
            with patch("asyncio.create_task", side_effect=_close_and_raise):
                job = await run_audit(
                    profile=profile,
                    target_host="10.0.0.1",
                    ssh_user="ubuntu",
                    output_dir=Path("/tmp"),
                )

        assert job.status == AuditStatus.FAILED


# ===========================================================================
# core/auditor.py — run_image_scan exception path
# ===========================================================================


class TestAuditorRunImageScanException:
    @pytest.mark.anyio
    async def test_run_image_scan_exception_sets_job_failed(self):
        """run_image_scan sets job status to FAILED when provider raises inside the try block."""
        from unittest.mock import MagicMock

        from stratum.core.auditor import AuditStatus, run_image_scan
        from stratum.core.blueprint import ComplianceProfile

        profile = ComplianceProfile.model_validate(
            {
                "stratum_version": "0.1.0",
                "kind": "ComplianceProfile",
                "metadata": {"name": "auditor-exc-test", "version": "1.0.0"},
                "target": {"os": "ubuntu22.04", "provider": "aws", "base_image": "ami-00"},
                "compliance": {
                    "benchmark": "xccdf_org.ssgproject.content_benchmark_UBUNTU2204",
                    "profile": "xccdf_org.ssgproject.content_profile_cis_level1_server",
                    "datastream": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml",
                },
            }
        )

        # Build a fake provider class that raises when scan_image() is called
        fake_instance = MagicMock()
        fake_instance.scan_image.side_effect = RuntimeError("Provider unavailable")
        fake_cls = MagicMock(return_value=fake_instance)
        fake_cls.handles_full_lifecycle = True

        with patch("stratum.core.auditor.registry") as mock_reg:
            mock_reg.get.return_value = fake_cls
            job = await run_image_scan(
                image_id="ami-exc-001",
                provider_name="aws",
                region="us-east-1",
                profile=profile,
                instance_type="t3.medium",
                output_dir=Path("/tmp"),
            )

        assert job.status == AuditStatus.FAILED
        assert "Provider unavailable" in (job.error or "")

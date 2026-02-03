"""
Enhanced HTML reporter for autonomous testing.

Generates detailed HTML reports with:
- Step-by-step execution details
- Request/response captures
- Validation results per layer
- Collapsible sections for detailed information
- Timeline visualization
- Consistency metrics for rinse/repeat
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class StepArtifact:
    """Artifact captured during step execution."""

    name: str
    content_type: str  # "json", "text", "binary"
    data: str | bytes
    size_bytes: int = 0


@dataclass
class StepExecutionDetail:
    """Detailed execution information for a single step."""

    step_name: str
    scenario_name: str
    category: str
    passed: bool
    skipped: bool
    duration_ms: float
    start_time: datetime
    end_time: datetime

    # Request details
    method: str = ""
    url: str = ""
    request_body: str | None = None
    request_headers: dict[str, str] | None = None

    # Response details
    status_code: int | None = None
    response_body: str | None = None
    response_headers: dict[str, str] | None = None

    # Validation results
    validation_errors: list[str] = field(default_factory=list)
    validation_warnings: list[str] = field(default_factory=list)

    # Artifacts
    artifacts: list[StepArtifact] = field(default_factory=list)

    # Saved variables
    saved_variables: dict[str, str] = field(default_factory=dict)


@dataclass
class ScenarioExecutionDetail:
    """Detailed execution information for a scenario."""

    scenario_name: str
    category: str
    passed: bool
    duration_ms: float
    steps_total: int
    steps_passed: int
    steps_failed: int
    steps_skipped: int
    step_details: list[StepExecutionDetail] = field(default_factory=list)


@dataclass
class TestRunDetail:
    """Detailed execution information for a complete test run."""

    run_number: int
    start_time: datetime
    end_time: datetime | None
    duration_ms: float
    scenarios_total: int
    scenarios_passed: int
    scenarios_failed: int
    scenario_details: list[ScenarioExecutionDetail] = field(default_factory=list)

    # Environment info
    base_url: str = ""
    database_host: str = ""
    doppler_config: str = ""


class EnhancedHtmlReporter:
    """Generates detailed HTML reports for test execution."""

    def __init__(self, template_path: str | None = None):
        """Initialize reporter with optional custom template."""
        self.template_path = template_path

    def generate_report(
        self,
        runs: list[TestRunDetail],
        output_path: Path,
        title: str = "Autonomous Live Test Report",
    ) -> None:
        """Generate HTML report and write to file.

        Args:
            runs: List of test run details (may be multiple for rinse/repeat)
            output_path: Path to write the HTML file
            title: Report title
        """
        html_content = self._render_html(runs, title)
        output_path.write_text(html_content, encoding="utf-8")

    def _render_html(self, runs: list[TestRunDetail], title: str) -> str:
        """Render the complete HTML report."""
        if not runs:
            return self._render_empty_report(title)

        # Get first run for summary
        first = runs[0]
        consistency_ok = self._check_consistency(runs)

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{self._escape(title)}</title>
    <style>
        {self._get_css()}
    </style>
    <script>
        {self._get_javascript()}
    </script>
</head>
<body>
    <div class="container">
        <header>
            <h1>{self._escape(title)}</h1>
            <div class="meta">
                Generated: {datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")}
            </div>
        </header>

        {self._render_summary_section(first, runs, consistency_ok)}

        {self._render_consistency_section(runs) if len(runs) > 1 else ""}

        {self._render_scenarios_section(first)}

        {self._render_artifacts_section(runs)}
    </div>
</body>
</html>
"""
        return html

    def _render_empty_report(self, title: str) -> str:
        """Render report for no test runs."""
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{self._escape(title)}</title>
    <style>{self._get_css()}</style>
</head>
<body>
    <div class="container">
        <h1>{self._escape(title)}</h1>
        <div class="alert alert-warning">No test runs to display</div>
    </div>
</body>
</html>
"""

    def _render_summary_section(
        self,
        run: TestRunDetail,
        runs: list[TestRunDetail],
        consistency_ok: bool,
    ) -> str:
        """Render the summary section."""
        total_runs = len(runs)
        pass_rate = (
            (run.scenarios_passed / run.scenarios_total * 100) if run.scenarios_total > 0 else 0
        )

        return f"""
        <section class="summary">
            <h2>Summary</h2>
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-label">Test Runs</div>
                    <div class="stat-value">{total_runs}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Scenarios</div>
                    <div class="stat-value">{run.scenarios_total}</div>
                </div>
                <div class="stat-card {"stat-pass" if run.scenarios_failed == 0 else "stat-fail"}">
                    <div class="stat-label">Passed</div>
                    <div class="stat-value">{run.scenarios_passed}</div>
                </div>
                <div class="stat-card {"stat-pass" if run.scenarios_failed == 0 else "stat-fail"}">
                    <div class="stat-label">Failed</div>
                    <div class="stat-value">{run.scenarios_failed}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Pass Rate</div>
                    <div class="stat-value">{pass_rate:.1f}%</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Duration</div>
                    <div class="stat-value">{run.duration_ms / 1000:.1f}s</div>
                </div>
            </div>
            {self._render_consistency_banner(consistency_ok, total_runs) if total_runs > 1 else ""}
        </section>
        """

    def _render_consistency_banner(self, consistency_ok: bool, total_runs: int) -> str:
        """Render the consistency check banner."""
        css_class = "consistency-pass" if consistency_ok else "consistency-fail"
        text = "100% Consistent" if consistency_ok else "Inconsistency Detected"
        return f'<div class="consistency-banner {css_class}">Rinse/Repeat ({total_runs} runs): {text}</div>'

    def _render_consistency_section(self, runs: list[TestRunDetail]) -> str:
        """Render the consistency breakdown for multiple runs."""
        rows = []
        for _i, run in enumerate(runs):
            status = "PASS" if run.scenarios_failed == 0 else "FAIL"
            status_class = "status-pass" if run.scenarios_failed == 0 else "status-fail"
            rows.append(f"""
                <tr>
                    <td>Run {run.run_number}</td>
                    <td>{run.scenarios_passed}/{run.scenarios_total}</td>
                    <td>{run.scenarios_failed}</td>
                    <td>{run.duration_ms / 1000:.1f}s</td>
                    <td><span class="{status_class}">{status}</span></td>
                </tr>
            """)

        return f"""
        <section class="consistency-detail">
            <h2>Rinse/Repeat Consistency</h2>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Run</th>
                        <th>Passed/Total</th>
                        <th>Failed</th>
                        <th>Duration</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(rows)}
                </tbody>
            </table>
        </section>
        """

    def _render_scenarios_section(self, run: TestRunDetail) -> str:
        """Render the scenarios section with step details."""
        scenario_cards = []

        for scenario in run.scenario_details:
            status_class = "scenario-pass" if scenario.passed else "scenario-fail"
            status_icon = "✓" if scenario.passed else "✗"

            steps_html = self._render_steps(scenario)

            scenario_cards.append(f"""
            <div class="scenario-card {status_class}">
                <div class="scenario-header" onclick="toggleScenario('{scenario.scenario_name}')">
                    <div class="scenario-title">
                        <span class="status-icon">{status_icon}</span>
                        <span>{self._escape(scenario.scenario_name)}</span>
                        <span class="badge">{self._escape(scenario.category)}</span>
                    </div>
                    <div class="scenario-meta">
                        {scenario.steps_passed}/{scenario.steps_total} steps passed
                        ({scenario.duration_ms / 1000:.2f}s)
                        <span class="toggle">▼</span>
                    </div>
                </div>
                <div class="scenario-body" id="scenario-{self._sanitize_id(scenario.scenario_name)}">
                    {steps_html}
                </div>
            </div>
            """)

        return f"""
        <section class="scenarios">
            <h2>Scenario Results ({len(run.scenario_details)})</h2>
            <div class="scenario-list">
                {"".join(scenario_cards)}
            </div>
        </section>
        """

    def _render_steps(self, scenario: ScenarioExecutionDetail) -> str:
        """Render the steps for a scenario."""
        if not scenario.step_details:
            return "<p>No step details available</p>"

        steps_html = []
        for i, step in enumerate(scenario.step_details, 1):
            # Handle both StepExecutionDetail and dict (from StepResult)
            if isinstance(step, dict):
                step_name = step.get("step_name", f"Step {i}")
                passed = step.get("passed", False)
                skipped = step.get("skipped", False)
                status_code = step.get("status_code")
                duration_ms = step.get("duration_ms", 0)
                error_msg = step.get("error_message", "")
                request_method = step.get("request_method", "")
                request_url = step.get("request_url", "")
                request_headers = step.get("request_headers")
                request_body = step.get("request_body")
                response_headers = step.get("response_headers")
                response_body = step.get("response_body_formatted") or step.get("response_body")
            else:
                step_name = step.step_name
                passed = step.passed
                skipped = step.skipped
                status_code = step.status_code
                duration_ms = step.duration_ms
                error_msg = getattr(step, "error_message", "")
                request_method = step.method
                request_url = step.url
                request_headers = step.request_headers
                request_body = step.request_body
                response_headers = step.response_headers
                response_body = step.response_body

            step_status_class = "step-pass" if passed else "step-fail"
            if skipped:
                step_status_class = "step-skipped"

            # Build details HTML with request/response info
            details_html = ""
            if not skipped and (request_method or request_url):
                details_html = "<div class='step-details'>"

                # Request line
                if request_method or request_url:
                    details_html += f"""
                    <div class='detail-row'>
                        <span class='detail-label'>Request:</span>
                        <span class='detail-value method'>{request_method or "GET"} {self._escape(request_url or "")}</span>
                    </div>"""

                # Request headers
                if request_headers:
                    headers_html = self._format_headers_html(request_headers)
                    details_html += f"""
                    <div class='detail-row detail-block'>
                        <span class='detail-label'>Request Headers:</span>
                        <pre class='code-block'>{headers_html}</pre>
                    </div>"""

                # Request body
                if request_body:
                    details_html += f"""
                    <div class='detail-row detail-block'>
                        <span class='detail-label'>Request Body:</span>
                        <pre class='code-block'>{self._escape(request_body)}</pre>
                    </div>"""

                # Response status
                if status_code is not None:
                    status_class = "status-pass" if 200 <= status_code < 300 else "status-fail"
                    details_html += f"""
                    <div class='detail-row'>
                        <span class='detail-label'>Response Status:</span>
                        <span class='detail-value {status_class}'>{status_code}</span>
                    </div>"""

                # Response headers
                if response_headers:
                    headers_html = self._format_headers_html(response_headers)
                    details_html += f"""
                    <div class='detail-row detail-block'>
                        <span class='detail-label'>Response Headers:</span>
                        <pre class='code-block'>{headers_html}</pre>
                    </div>"""

                # Response body
                if response_body:
                    details_html += f"""
                    <div class='detail-row detail-block'>
                        <span class='detail-label'>Response Body:</span>
                        <pre class='code-block'>{self._escape(response_body)}</pre>
                    </div>"""

                # Duration
                details_html += f"""
                <div class='detail-row'>
                    <span class='detail-label'>Duration:</span>
                    <span class='detail-value'>{duration_ms:.0f}ms</span>
                </div>"""

                details_html += "</div>"

            # Error message
            issues_html = ""
            if error_msg:
                issues_html = f"<div class='step-error'>{self._escape(error_msg)}</div>"

            steps_html.append(f"""
            <div class="step {step_status_class}">
                <div class="step-header" onclick="toggleStep('step-{self._sanitize_id(scenario.scenario_name)}-{i}')">
                    <span class="step-num">{i}</span>
                    <span class="step-name">{self._escape(step_name)}</span>
                    <span class="step-toggle">▼</span>
                </div>
                <div class="step-body" id="step-{self._sanitize_id(f"{scenario.scenario_name}-{i}")}">
                    {details_html}
                    {issues_html}
                </div>
            </div>
            """)

        return f"<div class='steps-list'>{''.join(steps_html)}</div>"

    def _format_headers_html(self, headers: dict[str, str] | None) -> str:
        """Format headers dictionary as HTML."""
        if not headers:
            return ""
        lines = [f"{k}: {v}" for k, v in headers.items()]
        return self._escape("\n".join(lines))

    def _render_artifacts_section(self, runs: list[TestRunDetail]) -> str:
        """Render the artifacts section."""
        return """
        <section class="artifacts">
            <h2>Artifacts</h2>
            <p>Test artifacts and logs are available in the test output directory.</p>
        </section>
        """

    def _check_consistency(self, runs: list[TestRunDetail]) -> bool:
        """Check if all runs produced identical results."""
        if len(runs) < 2:
            return True

        first = runs[0]
        for run in runs[1:]:
            if run.scenarios_total != first.scenarios_total:
                return False
            if run.scenarios_passed != first.scenarios_passed:
                return False
            if run.scenarios_failed != first.scenarios_failed:
                return False

        return True

    def _sanitize_id(self, value: str) -> str:
        """Sanitize a value for use in HTML id attribute."""
        return re.sub(r"[^a-zA-Z0-9-_]", "-", value)

    def _escape(self, value: Any) -> str:
        """HTML-escape a value."""
        if value is None:
            return ""
        value_str = str(value)
        return (
            value_str.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#x27;")
        )

    def _get_css(self) -> str:
        """Get the CSS styles for the report."""
        return """
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #f5f5f5;
            padding: 20px;
            line-height: 1.5;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        header {
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        h1 { color: #333; margin-bottom: 10px; }
        h2 { color: #444; margin-bottom: 15px; font-size: 1.3rem; }
        .meta { color: #666; font-size: 0.9rem; }

        .summary {
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
        }
        .stat-card {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 6px;
            text-align: center;
        }
        .stat-label { font-size: 0.85rem; color: #666; }
        .stat-value { font-size: 1.8rem; font-weight: bold; margin-top: 5px; }
        .stat-pass .stat-value { color: #28a745; }
        .stat-fail .stat-value { color: #dc3545; }

        .consistency-banner {
            margin-top: 15px;
            padding: 12px;
            border-radius: 6px;
            text-align: center;
            font-weight: 600;
        }
        .consistency-pass { background: #d4edda; color: #155724; }
        .consistency-fail { background: #f8d7da; color: #721c24; }

        .data-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }
        .data-table th, .data-table td {
            padding: 10px;
            text-align: left;
            border-bottom: 1px solid #dee2e6;
        }
        .data-table th { background: #f8f9fa; font-weight: 600; }
        .status-pass { color: #28a745; font-weight: 600; }
        .status-fail { color: #dc3545; font-weight: 600; }

        .scenario-list { display: flex; flex-direction: column; gap: 10px; }
        .scenario-card {
            background: white;
            border-radius: 6px;
            overflow: hidden;
            border-left: 4px solid #dee2e6;
        }
        .scenario-pass { border-left-color: #28a745; }
        .scenario-fail { border-left-color: #dc3545; }

        .scenario-header {
            padding: 15px;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: #f8f9fa;
        }
        .scenario-header:hover { background: #e9ecef; }
        .scenario-title {
            display: flex;
            align-items: center;
            gap: 10px;
            font-weight: 600;
        }
        .status-icon { font-size: 1.2rem; }
        .badge {
            background: #6c757d;
            color: white;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 0.75rem;
        }
        .scenario-meta {
            color: #666;
            font-size: 0.9rem;
            display: flex;
            align-items: center;
            gap: 15px;
        }
        .toggle { transition: transform 0.2s; }

        .scenario-body {
            display: none;
            padding: 15px;
            border-top: 1px solid #dee2e6;
        }
        .scenario-body.active { display: block; }

        .steps-list { display: flex; flex-direction: column; gap: 8px; }
        .step {
            background: #f8f9fa;
            border-radius: 4px;
            overflow: hidden;
        }
        .step-pass { border-left: 3px solid #28a745; }
        .step-fail { border-left: 3px solid #dc3545; }
        .step-skipped { border-left: 3px solid #ffc107; opacity: 0.7; }

        .step-header {
            padding: 10px 15px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .step-num {
            background: #dee2e6;
            width: 24px;
            height: 24px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.8rem;
            font-weight: 600;
        }
        .step-name { flex: 1; font-weight: 500; }

        .step-body { display: none; padding: 15px; background: white; }
        .step-body.active { display: block; }

        .step-details {
            display: flex;
            flex-direction: column;
            gap: 10px;
            margin-bottom: 10px;
        }
        .detail-row {
            display: grid;
            grid-template-columns: auto 1fr;
            gap: 8px;
            align-items: start;
        }
        .detail-block {
            grid-template-columns: auto 1fr;
            align-items: start;
        }
        .detail-label { color: #666; font-size: 0.9rem; font-weight: 500; }
        .detail-value { font-family: monospace; font-size: 0.9rem; }
        .detail-value.method { font-weight: 600; color: #495057; }
        .code-block {
            background: #f1f3f5;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            padding: 10px;
            margin: 5px 0;
            font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
            font-size: 0.85rem;
            overflow-x: auto;
            white-space: pre-wrap;
            word-break: break-word;
            max-height: 400px;
            overflow-y: auto;
        }
        .status-pass { color: #28a745; font-weight: 600; }
        .status-fail { color: #dc3545; font-weight: 600; }
        .step-error {
            margin-top: 10px;
            padding: 10px;
            background: #f8d7da;
            border-left: 3px solid #dc3545;
            color: #721c24;
            border-radius: 4px;
        }

        .step-issues, .step-warnings {
            margin-top: 10px;
            padding-left: 20px;
        }
        .step-issues li { color: #dc3545; }
        .step-warnings li { color: #ffc107; }

        .alert {
            padding: 15px;
            border-radius: 6px;
            margin-bottom: 20px;
        }
        .alert-warning { background: #fff3cd; border-left: 4px solid #ffc107; }
        """

    def _get_javascript(self) -> str:
        """Get the JavaScript for interactive features."""
        return """
        function toggleScenario(name) {
            const body = document.getElementById('scenario-' + name.replace(/[^a-zA-Z0-9-_]/g, '-'));
            const header = body.previousElementSibling;
            const toggle = header.querySelector('.toggle');

            if (body.classList.contains('active')) {
                body.classList.remove('active');
                toggle.style.transform = '';
            } else {
                body.classList.add('active');
                toggle.style.transform = 'rotate(180deg)';
            }
        }

        function toggleStep(id) {
            const body = document.getElementById(id);
            const header = body.previousElementSibling;
            const toggle = header.querySelector('.step-toggle');

            if (body.classList.contains('active')) {
                body.classList.remove('active');
                toggle.style.transform = '';
            } else {
                body.classList.add('active');
                toggle.style.transform = 'rotate(180deg)';
            }
        }
        """

"""Tests for lion.functions.audit module.

Tests cover all critical issues from the devil's advocate review:
1. Auto-fix disabled by default (now limited self-heal for low-risk)
2. Confidence levels (pattern-matched vs ai-suggested)
3. LLM fallback behavior
4. Code snippet extraction
5. .gitignore respect
6. Performance constraints
7. Audit trail logging (with history/diff)
8. Security check registry
9. Smart file prioritization for AI analysis
10. Related file inclusion in deduplication
"""

import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from lion.functions.audit import (
    # Registry
    SECURITY_REGISTRY,
    SecurityCheckRegistry,
    SecurityCheck,
    SecurityFinding,
    # File handling
    load_gitignore_patterns,
    should_scan_file,
    get_scannable_files,
    DEFAULT_EXCLUDE_PATTERNS,
    ALWAYS_SCAN_FOR_SECRETS,
    # Snippet extraction
    extract_snippet,
    truncate_at_function_boundary,
    # Pattern-based checks
    check_secrets,
    check_sql_injection,
    check_xss,
    check_command_injection,
    check_path_traversal,
    check_insecure_config,
    check_auth_issues,
    # AI analysis
    run_ai_security_analysis,
    # Audit trail
    AuditTrail,
    AuditLogEntry,
    # File hashing and prioritization
    get_file_hash,
    get_changed_files,
    get_file_imports,
    prioritize_files_for_ai,
    # Self-heal
    SELF_HEAL_FIXES,
    generate_self_heal_fix,
    apply_self_heal_fixes,
    # Main function
    execute_audit,
)
from lion.parser import PipelineStep
from lion.memory import SharedMemory


@pytest.fixture
def temp_project(tmp_path):
    """Create a temporary project directory with various files."""
    # Create source files
    src_dir = tmp_path / "src"
    src_dir.mkdir()

    # Python file with potential issues
    py_file = src_dir / "main.py"
    py_file.write_text('''
import os
import subprocess

API_KEY = "sk-1234567890abcdefghijklmnop"  # Hardcoded secret

def get_user(user_id):
    # SQL injection vulnerability
    query = f"SELECT * FROM users WHERE id = {user_id}"
    return execute(query)

def run_command(cmd):
    # Command injection
    os.system(cmd)

DEBUG = True  # Insecure config
''')

    # JavaScript file
    js_file = src_dir / "app.js"
    js_file.write_text('''
const password = "supersecret123";

function renderHtml(userInput) {
    document.innerHTML = userInput;  // XSS
}

eval(req.query.code);  // Code injection
''')

    # Create .gitignore
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text('''
node_modules/
*.log
.env
dist/
''')

    # Create node_modules (should be ignored)
    node_modules = tmp_path / "node_modules"
    node_modules.mkdir()
    ignored_file = node_modules / "package.json"
    ignored_file.write_text('{"name": "test"}')

    # Create .env file (should always be scanned for secrets)
    env_file = tmp_path / ".env"
    env_file.write_text('DATABASE_URL=postgres://user:password@localhost/db')

    return tmp_path


@pytest.fixture
def temp_run_dir(tmp_path):
    """Create a temporary run directory for memory."""
    run_dir = tmp_path / ".lion" / "runs" / "test"
    run_dir.mkdir(parents=True)
    return run_dir


@pytest.fixture
def sample_config():
    """Sample Lion configuration."""
    return {
        "providers": {
            "default": "claude",
            "claude": {"api_key": "test-key"},
        },
        "self_healing": {
            "max_heal_cost": 1.0,
        },
        "audit": {
            "max_ai_files": 50,
            "ai_batch_size": 5,
            "max_file_chars": 15000,
            "high_risk_paths": ["**/auth/**", "**/payment/**", "**/api/**"],
            "self_heal_rules": ["secrets_to_env", "debug_false", "ssl_verify_true"],
        },
    }


class TestSecurityCheckRegistry:
    """Tests for the security check registry pattern."""

    def test_registry_initialized(self):
        """Test that global registry is initialized with checks."""
        assert len(SECURITY_REGISTRY.check_names) >= 7
        assert "secrets" in SECURITY_REGISTRY.check_names
        assert "sql-injection" in SECURITY_REGISTRY.check_names
        assert "xss" in SECURITY_REGISTRY.check_names

    def test_registry_can_enable_disable(self):
        """Test enabling/disabling specific checks."""
        registry = SecurityCheckRegistry()
        registry.register(
            name="test-check",
            category="test",
            description="Test check",
            check_fn=lambda cwd, files: [],
        )

        assert registry.get_check("test-check").enabled is True
        registry.disable("test-check")
        assert registry.get_check("test-check").enabled is False
        registry.enable("test-check")
        assert registry.get_check("test-check").enabled is True

    def test_registry_category_filtering(self):
        """Test filtering checks by category."""
        registry = SecurityCheckRegistry()
        registry.register(name="check-a", category="cat1", description="A", check_fn=lambda c, f: [])
        registry.register(name="check-b", category="cat1", description="B", check_fn=lambda c, f: [])
        registry.register(name="check-c", category="cat2", description="C", check_fn=lambda c, f: [])

        cat1_checks = registry.get_checks_by_category("cat1")
        assert len(cat1_checks) == 2

        cat2_checks = registry.get_checks_by_category("cat2")
        assert len(cat2_checks) == 1

    def test_registry_llm_filtering(self):
        """Test filtering out LLM-required checks."""
        registry = SecurityCheckRegistry()
        registry.register(name="regex-check", category="test", description="Regex", check_fn=lambda c, f: [], requires_llm=False)
        registry.register(name="ai-check", category="test", description="AI", check_fn=lambda c, f: [], requires_llm=True)

        all_checks = registry.get_all_enabled(include_llm=True)
        assert len(all_checks) == 2

        regex_only = registry.get_all_enabled(include_llm=False)
        assert len(regex_only) == 1
        assert regex_only[0].name == "regex-check"


class TestSecurityFinding:
    """Tests for SecurityFinding structure."""

    def test_finding_has_confidence_field(self):
        """Test that findings include confidence level."""
        finding = SecurityFinding(
            category="secrets",
            severity="critical",
            message="API key found",
            file="test.py",
            line=10,
            confidence="pattern-matched",
        )
        assert finding.confidence == "pattern-matched"

    def test_finding_has_snippet_field(self):
        """Test that findings include code snippet."""
        finding = SecurityFinding(
            category="secrets",
            severity="critical",
            message="API key found",
            file="test.py",
            line=10,
            snippet="   9    \n  10>>> API_KEY = 'secret'\n  11    ",
            snippet_start_line=9,
        )
        assert finding.snippet is not None
        assert finding.snippet_start_line == 9

    def test_finding_to_dict(self):
        """Test finding serialization."""
        finding = SecurityFinding(
            category="secrets",
            severity="critical",
            message="API key found",
            file="test.py",
            line=10,
            confidence="pattern-matched",
        )
        data = finding.to_dict()
        assert data["confidence"] == "pattern-matched"
        assert data["category"] == "secrets"


class TestGitignoreHandling:
    """Tests for .gitignore respect."""

    def test_load_gitignore_patterns(self, temp_project):
        """Test loading patterns from .gitignore."""
        patterns = load_gitignore_patterns(str(temp_project))
        assert any("node_modules" in p for p in patterns)
        assert any(".env" in p for p in patterns)

    def test_should_scan_excludes_gitignore(self, temp_project):
        """Test that gitignored files are excluded."""
        patterns = load_gitignore_patterns(str(temp_project))
        patterns.update(DEFAULT_EXCLUDE_PATTERNS)

        # node_modules should be excluded
        assert should_scan_file("node_modules/package.json", str(temp_project), patterns) is False

        # src files should be included
        assert should_scan_file("src/main.py", str(temp_project), patterns) is True

    def test_always_scan_for_secrets(self, temp_project):
        """Test that .env files are always scanned for secrets."""
        patterns = load_gitignore_patterns(str(temp_project))
        patterns.update(DEFAULT_EXCLUDE_PATTERNS)

        # .env should be scanned for secrets even if in .gitignore
        assert should_scan_file(".env", str(temp_project), patterns, for_secrets=True) is True

    def test_include_ignored_flag(self, temp_project):
        """Test --include-ignored flag behavior."""
        patterns = load_gitignore_patterns(str(temp_project))
        patterns.update(DEFAULT_EXCLUDE_PATTERNS)

        # With include_ignored=True, gitignored files should be included
        assert should_scan_file("node_modules/package.json", str(temp_project), patterns, include_ignored=True) is True


class TestSnippetExtraction:
    """Tests for code snippet extraction."""

    def test_extract_snippet_basic(self, temp_project):
        """Test basic snippet extraction."""
        filepath = str(temp_project / "src" / "main.py")
        snippet, start_line = extract_snippet(filepath, line=5)  # API_KEY line

        assert snippet is not None
        assert start_line > 0
        assert ">>>" in snippet  # Target line marker
        assert "API_KEY" in snippet

    def test_extract_snippet_context(self, temp_project):
        """Test that snippet includes context lines."""
        filepath = str(temp_project / "src" / "main.py")
        snippet, start_line = extract_snippet(filepath, line=5, context_lines=2)

        lines = snippet.split("\n")
        # Should have ~5 lines (2 before + target + 2 after)
        assert len(lines) >= 3

    def test_extract_snippet_truncates_long_lines(self, tmp_path):
        """Test that long lines are truncated in snippet."""
        long_file = tmp_path / "long.py"
        long_file.write_text("x = '" + "A" * 200 + "'")

        snippet, _ = extract_snippet(str(long_file), line=1, max_line_length=50)
        assert "..." in snippet


class TestPatternBasedChecks:
    """Tests for pattern-based security checks."""

    def test_check_secrets(self, temp_project):
        """Test secret detection."""
        files = ["src/main.py"]
        findings = check_secrets(str(temp_project), files)

        assert len(findings) > 0
        assert any(f.category == "secrets" for f in findings)
        assert any("API" in f.message or "key" in f.message.lower() for f in findings)
        # All pattern findings should have high confidence
        assert all(f.confidence == "pattern-matched" for f in findings)

    def test_check_sql_injection(self, temp_project):
        """Test SQL injection detection."""
        files = ["src/main.py"]
        findings = check_sql_injection(str(temp_project), files)

        assert len(findings) > 0
        assert any(f.category == "injection" for f in findings)
        assert all(f.confidence == "pattern-matched" for f in findings)

    def test_check_xss(self, temp_project):
        """Test XSS detection."""
        files = ["src/app.js"]
        findings = check_xss(str(temp_project), files)

        assert len(findings) > 0
        assert any("innerHTML" in f.message or "XSS" in f.message for f in findings)

    def test_check_command_injection(self, temp_project):
        """Test command injection detection."""
        files = ["src/main.py"]
        findings = check_command_injection(str(temp_project), files)

        assert len(findings) > 0
        assert any("os.system" in f.message or "command" in f.message.lower() for f in findings)

    def test_check_insecure_config(self, temp_project):
        """Test insecure config detection."""
        files = ["src/main.py"]
        findings = check_insecure_config(str(temp_project), files)

        assert len(findings) > 0
        assert any("debug" in f.message.lower() for f in findings)


class TestAuditTrail:
    """Tests for audit trail logging."""

    def test_audit_trail_creates_log_file(self, temp_project):
        """Test that audit trail creates log file."""
        trail = AuditTrail(str(temp_project))
        assert os.path.exists(trail.log_dir)

        trail.log_scan_start(10, ["secrets", "xss"])
        assert os.path.exists(trail.log_file)

    def test_audit_trail_logs_findings(self, temp_project):
        """Test logging findings to audit trail."""
        trail = AuditTrail(str(temp_project))

        finding = SecurityFinding(
            category="secrets",
            severity="critical",
            message="API key found",
            file="test.py",
            line=10,
            confidence="pattern-matched",
        )
        trail.log_finding(finding)

        # Read log file
        with open(trail.log_file) as f:
            content = f.read()
            assert "finding" in content
            assert "API key" in content


class TestPerformanceConstraints:
    """Tests for performance constraints."""

    def test_max_files_limit(self, temp_project):
        """Test that --max-files limits scanned files."""
        # Create many files
        for i in range(100):
            (temp_project / "src" / f"file_{i}.py").write_text(f"# File {i}")

        files = get_scannable_files(str(temp_project), max_files=10)
        assert len(files) <= 10

    def test_quick_mode_skips_ai(self, temp_project, temp_run_dir, sample_config):
        """Test that --quick mode skips AI analysis."""
        memory = SharedMemory(temp_run_dir)

        with patch("lion.functions.audit.Display"):
            result = execute_audit(
                prompt="Security audit",
                previous={},
                step=PipelineStep(function="audit", args=["--quick"]),
                memory=memory,
                config=sample_config,
                cwd=str(temp_project),
            )

        assert result["quick_mode"] is True
        assert result["ai_findings"] == 0


class TestLLMFallback:
    """Tests for LLM failure handling."""

    def test_llm_unavailable_falls_back_to_pattern(self, temp_project, temp_run_dir, sample_config):
        """Test fallback when LLM is unavailable."""
        memory = SharedMemory(temp_run_dir)

        def mock_get_provider(*args, **kwargs):
            raise Exception("Provider unavailable")

        with patch("lion.functions.audit.get_provider", side_effect=mock_get_provider):
            with patch("lion.functions.audit.Display"):
                result = execute_audit(
                    prompt="Security audit",
                    previous={},
                    step=PipelineStep(function="audit"),
                    memory=memory,
                    config=sample_config,
                    cwd=str(temp_project),
                )

        # Should still succeed with pattern-only findings
        assert result["success"] is True
        assert result["llm_available"] is False
        assert result["pattern_findings"] > 0


class TestAutoFixAndSelfHeal:
    """Tests for auto-fix safety and limited self-heal."""

    def test_autofix_disabled_by_default(self, temp_project, temp_run_dir, sample_config):
        """Test that auto-fix is disabled by default (no self_heal)."""
        memory = SharedMemory(temp_run_dir)

        with patch("lion.functions.audit.Display"):
            result = execute_audit(
                prompt="Security audit",
                previous={},
                step=PipelineStep(function="audit"),
                memory=memory,
                config=sample_config,
                cwd=str(temp_project),
            )

        # Without self_heal, no fixes should be applied
        assert result["self_heal_enabled"] is False
        assert result["fixes_applied"] == []

    def test_self_heal_only_fixes_low_risk(self, temp_project, temp_run_dir, sample_config):
        """Test that ^ operator only fixes LOW-RISK issues (secrets, debug, ssl)."""
        memory = SharedMemory(temp_run_dir)

        step = PipelineStep(function="audit", args=["--quick"])
        step.self_heal = True  # Simulate ^ operator

        with patch("lion.functions.audit.Display"):
            result = execute_audit(
                prompt="Security audit",
                previous={},
                step=step,
                memory=memory,
                config=sample_config,
                cwd=str(temp_project),
            )

        # Self-heal should be enabled
        assert result["self_heal_enabled"] is True
        # May have applied fixes for secrets/debug (if patterns matched)
        # But complex issues like SQL injection should NOT be fixed
        for fix in result["fixes_applied"]:
            assert fix["rule"] in ["secrets_to_env", "debug_false", "ssl_verify_true"]

    def test_self_heal_rules_are_limited(self):
        """Test that only low-risk rules are defined in SELF_HEAL_FIXES."""
        # Only these categories should have self-heal fixes
        allowed_categories = {"secrets", "config"}
        for rule_name, rule_config in SELF_HEAL_FIXES.items():
            assert rule_config["category"] in allowed_categories, \
                f"Rule {rule_name} has category {rule_config['category']} which is not low-risk"

    def test_complex_issues_not_auto_fixed(self, temp_project, temp_run_dir, sample_config):
        """Test that SQL injection and other complex issues are NOT auto-fixed."""
        memory = SharedMemory(temp_run_dir)

        step = PipelineStep(function="audit", args=["--quick"])
        step.self_heal = True

        with patch("lion.functions.audit.Display"):
            result = execute_audit(
                prompt="Security audit",
                previous={},
                step=step,
                memory=memory,
                config=sample_config,
                cwd=str(temp_project),
            )

        # Should still find SQL injection but NOT fix it
        sql_findings = [f for f in result["findings"] if "SQL" in f.get("message", "") or f.get("category") == "injection"]
        assert len(sql_findings) > 0, "Should detect SQL injection"
        # SQL injection should not be in fixes
        for fix in result["fixes_applied"]:
            assert "sql" not in fix["rule"].lower()


class TestConfidenceLevels:
    """Tests for confidence level marking."""

    def test_pattern_findings_have_high_confidence(self, temp_project):
        """Test that pattern-based findings are marked pattern-matched."""
        files = ["src/main.py"]
        findings = check_secrets(str(temp_project), files)

        for finding in findings:
            assert finding.confidence == "pattern-matched"

    def test_ai_findings_have_lower_confidence(self, temp_project):
        """Test that AI findings are marked ai-suggested."""
        mock_provider = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.content = '''
{
  "findings": [
    {
      "category": "logic",
      "severity": "medium",
      "message": "Potential race condition",
      "file": "src/main.py",
      "line": 15,
      "fix_suggestion": "Add locking"
    }
  ],
  "analysis_notes": "Found potential issue"
}
'''
        mock_result.tokens_used = 100
        mock_provider.ask.return_value = mock_result

        findings, tokens = run_ai_security_analysis(
            str(temp_project),
            ["src/main.py"],
            [],
            mock_provider,
            max_files=10,
        )

        for finding in findings:
            assert finding.confidence == "ai-suggested"

        # Verify tokens were tracked
        assert tokens > 0


class TestFileChangeDeduplication:
    """Tests for file change tracking (deduplication)."""

    def test_get_file_hash(self, temp_project):
        """Test file hashing."""
        filepath = str(temp_project / "src" / "main.py")
        hash1 = get_file_hash(filepath)
        hash2 = get_file_hash(filepath)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hash length

    def test_changed_files_detection(self, temp_project, tmp_path):
        """Test detecting changed files."""
        cache_path = str(tmp_path / "hashes.json")
        files = ["src/main.py", "src/app.js"]

        # First scan - all files are "changed"
        changed, hashes = get_changed_files(str(temp_project), files, cache_path)
        assert len(changed) == 2

        # Save hashes and rescan - no changes
        from lion.functions.audit import save_file_hashes
        save_file_hashes(cache_path, hashes)

        changed2, _ = get_changed_files(str(temp_project), files, cache_path)
        assert len(changed2) == 0

        # Modify a file - should detect change
        (temp_project / "src" / "main.py").write_text("# Modified")
        changed3, _ = get_changed_files(str(temp_project), files, cache_path)
        assert "src/main.py" in changed3


class TestExecuteAudit:
    """Integration tests for execute_audit function."""

    def test_audit_returns_required_fields(self, temp_project, temp_run_dir, sample_config):
        """Test that audit returns all required fields."""
        memory = SharedMemory(temp_run_dir)

        with patch("lion.functions.audit.Display"):
            result = execute_audit(
                prompt="Security audit",
                previous={},
                step=PipelineStep(function="audit", args=["--quick"]),
                memory=memory,
                config=sample_config,
                cwd=str(temp_project),
            )

        # Check required fields
        assert "success" in result
        assert "findings" in result
        assert "findings_count" in result
        assert "severity_counts" in result
        assert "confidence_counts" in result
        assert "files_scanned" in result
        assert "pattern_findings" in result
        assert "ai_findings" in result
        assert "audit_log" in result
        assert "llm_available" in result

    def test_audit_category_filter(self, temp_project, temp_run_dir, sample_config):
        """Test --category flag filters checks."""
        memory = SharedMemory(temp_run_dir)

        with patch("lion.functions.audit.Display"):
            result = execute_audit(
                prompt="Security audit",
                previous={},
                step=PipelineStep(function="audit", args=["--quick", "--category", "secrets"]),
                memory=memory,
                config=sample_config,
                cwd=str(temp_project),
            )

        # Should only have findings from secrets category
        for finding in result["findings"]:
            assert finding["category"] == "secrets"

    def test_audit_disable_check(self, temp_project, temp_run_dir, sample_config):
        """Test --disable flag disables specific check."""
        memory = SharedMemory(temp_run_dir)

        with patch("lion.functions.audit.Display"):
            result = execute_audit(
                prompt="Security audit",
                previous={},
                step=PipelineStep(function="audit", args=["--quick", "--disable", "secrets"]),
                memory=memory,
                config=sample_config,
                cwd=str(temp_project),
            )

        # Should not have findings from secrets check
        for finding in result["findings"]:
            assert finding["category"] != "secrets" or finding["rule_id"] is None or "SECRETS" not in finding.get("rule_id", "")

    def test_audit_logs_to_memory(self, temp_project, temp_run_dir, sample_config):
        """Test that audit logs to shared memory."""
        memory = SharedMemory(temp_run_dir)

        with patch("lion.functions.audit.Display"):
            execute_audit(
                prompt="Security audit",
                previous={},
                step=PipelineStep(function="audit", args=["--quick"]),
                memory=memory,
                config=sample_config,
                cwd=str(temp_project),
            )

        # Check memory entries
        entries = memory.read_all()
        assert len(entries) > 0
        assert any(e.phase == "audit" for e in entries)


class TestFunctionRegistry:
    """Test that audit is properly registered."""

    def test_audit_in_functions_registry(self):
        """Test that audit is in the FUNCTIONS registry."""
        from lion.functions import FUNCTIONS
        assert "audit" in FUNCTIONS
        assert callable(FUNCTIONS["audit"])


class TestAuditHistory:
    """Tests for audit trail history and diff features."""

    def test_audit_history_mode(self, temp_project, temp_run_dir, sample_config):
        """Test --history flag returns audit history."""
        memory = SharedMemory(temp_run_dir)

        # First do a scan to create history
        with patch("lion.functions.audit.Display"):
            execute_audit(
                prompt="Security audit",
                previous={},
                step=PipelineStep(function="audit", args=["--quick"]),
                memory=memory,
                config=sample_config,
                cwd=str(temp_project),
            )

        # Now get history
        with patch("lion.functions.audit.Display"):
            result = execute_audit(
                prompt="Security audit",
                previous={},
                step=PipelineStep(function="audit", args=["--history"]),
                memory=memory,
                config=sample_config,
                cwd=str(temp_project),
            )

        assert result["mode"] == "history"
        assert "history" in result
        assert len(result["history"]) >= 1

    def test_audit_diff_mode(self, temp_project, temp_run_dir, sample_config):
        """Test --diff flag compares with last scan."""
        memory = SharedMemory(temp_run_dir)

        # Do initial scan
        with patch("lion.functions.audit.Display"):
            execute_audit(
                prompt="Security audit",
                previous={},
                step=PipelineStep(function="audit", args=["--quick"]),
                memory=memory,
                config=sample_config,
                cwd=str(temp_project),
            )

        # Do diff scan
        with patch("lion.functions.audit.Display"):
            result = execute_audit(
                prompt="Security audit",
                previous={},
                step=PipelineStep(function="audit", args=["--quick", "--diff"]),
                memory=memory,
                config=sample_config,
                cwd=str(temp_project),
            )

        assert "diff" in result
        if result["diff"]:
            assert "new_findings" in result["diff"]
            assert "resolved_findings" in result["diff"]


class TestFilePrioritization:
    """Tests for smart file prioritization for AI analysis."""

    def test_prioritize_high_risk_paths(self, tmp_path):
        """Test that high-risk paths are prioritized."""
        files = [
            "src/utils.py",
            "src/auth/login.py",
            "src/api/endpoints.py",
            "tests/test_utils.py",
            "src/payment/checkout.py",
        ]

        high_risk_paths = ["**/auth/**", "**/payment/**", "**/api/**"]

        prioritized = prioritize_files_for_ai(files, high_risk_paths, max_files=10)

        # High-risk files should be first
        auth_idx = prioritized.index("src/auth/login.py")
        utils_idx = prioritized.index("src/utils.py")
        assert auth_idx < utils_idx, "Auth file should be prioritized over utils"

    def test_prioritize_respects_max_files(self, tmp_path):
        """Test that prioritization respects max_files limit."""
        files = [f"src/file_{i}.py" for i in range(100)]

        prioritized = prioritize_files_for_ai(files, [], max_files=10)
        assert len(prioritized) == 10


class TestRelatedFileInclusion:
    """Tests for including related files in change detection."""

    def test_get_file_imports_python(self, tmp_path):
        """Test extracting imports from Python files."""
        py_file = tmp_path / "main.py"
        py_file.write_text("""
import os
from utils import helper
from auth.login import authenticate
""")

        imports = get_file_imports("main.py", str(tmp_path))

        # Should extract module paths
        assert any("utils" in imp for imp in imports)
        assert any("auth" in imp for imp in imports)

    def test_changed_files_includes_related(self, tmp_path):
        """Test that changed files include related files."""
        # Create a file structure
        src = tmp_path / "src"
        src.mkdir()

        main = src / "main.py"
        main.write_text("""
from utils import helper
""")

        utils = src / "utils.py"
        utils.write_text("def helper(): pass")

        cache_path = str(tmp_path / "cache.json")
        files = ["src/main.py", "src/utils.py"]

        # First scan
        changed, hashes = get_changed_files(str(tmp_path), files, cache_path, include_related=True)
        assert len(changed) == 2  # Both files are "new"


class TestSemanticTruncation:
    """Tests for semantic file truncation."""

    def test_truncate_at_function_boundary(self):
        """Test truncation at function boundaries."""
        code = """
def function_one():
    pass

def function_two():
    long_content = "x" * 1000
    more_content = "y" * 1000
    pass

def function_three():
    pass
"""
        # Truncate mid-way
        truncated = truncate_at_function_boundary(code, max_chars=150)

        # Should end at a function boundary
        assert "def function_one" in truncated
        assert "TRUNCATED" in truncated

    def test_no_truncation_for_small_files(self):
        """Test that small files are not truncated."""
        code = "def small(): pass"
        result = truncate_at_function_boundary(code, max_chars=1000)
        assert result == code
        assert "TRUNCATED" not in result


class TestFullScanMode:
    """Tests for --full scan mode."""

    def test_full_scan_ignores_deduplication(self, temp_project, temp_run_dir, sample_config):
        """Test that --full flag ignores file change deduplication."""
        memory = SharedMemory(temp_run_dir)

        with patch("lion.functions.audit.Display"):
            result = execute_audit(
                prompt="Security audit",
                previous={},
                step=PipelineStep(function="audit", args=["--quick", "--full"]),
                memory=memory,
                config=sample_config,
                cwd=str(temp_project),
            )

        assert result["full_scan"] is True

"""audit() - Security scanning function.

Performs security SCANNING of the codebase using both pattern-based detection
(high confidence) and AI-powered analysis (lower confidence, requires validation).

IMPORTANT - COVERAGE LIMITATIONS:
This tool checks for ~40 common vulnerability patterns but CANNOT:
- Perform data flow analysis (can't trace variables from user input to sinks)
- Detect indirect vulnerabilities (e.g., variables assigned from user input then used)
- Catch all ORM raw query variations (e.g., Django's RawSQL(), Peewee's raw())
- Identify business logic flaws beyond common patterns
- Replace static analysis tools like bandit, semgrep, or commercial SAST

This should be ONE LAYER of your security strategy, not the primary defense.
Consider using in combination with:
- bandit (Python): pip install bandit && bandit -r .
- semgrep: pip install semgrep && semgrep --config=auto .
- gitleaks/trufflehog (secrets): gitleaks detect

IMPORTANT SECURITY NOTES:
1. Self-heal (^) is limited to LOW-RISK issues only (secrets→env vars, debug→false, SSL→true)
2. Complex security fixes (SQL injection, auth issues) require manual review
3. All AI-suggested findings are marked with confidence: "ai-suggested"
4. Pattern-matched findings are marked with confidence: "pattern-matched"
5. All operations are logged to an audit trail
"""

import json
import os
import re
import time
import fnmatch
import hashlib
from typing import Optional, Callable
from dataclasses import dataclass, field, asdict

from ..memory import MemoryEntry
from ..display import Display
from ..providers import get_provider
from .utils import detect_project_language, get_source_files


# ============================================================================
# SECURITY CHECK REGISTRY
# ============================================================================
# Registry pattern supports:
# - Enabling/disabling specific checks (USED: --disable flag, category filtering)
# - Running only certain categories (USED: --category flag)
# - LLM requirement filtering (USED: --quick mode excludes LLM checks)
# - Severity weighting (RESERVED: for future weighted scoring/prioritization)
# - Named check lookup (RESERVED: for future check-specific configuration)
#
# Note: If maintaining unused features becomes burdensome, consider removing
# severity_weight and consolidating to a simpler dict-based approach.

@dataclass
class SecurityCheck:
    """Registered security check."""
    name: str
    category: str
    description: str
    check_fn: Callable
    severity_weight: float = 1.0
    enabled: bool = True
    requires_llm: bool = False


@dataclass
class SecurityFinding:
    """A security finding with all required context.

    Includes code snippet as required by devil's advocate review.
    """
    category: str
    severity: str  # critical, high, medium, low, info
    message: str
    file: str
    line: Optional[int] = None
    col: Optional[int] = None
    # Confidence level: "pattern-matched" (high) or "ai-suggested" (needs validation)
    confidence: str = "pattern-matched"
    # Code snippet with context (3-5 lines)
    snippet: Optional[str] = None
    snippet_start_line: Optional[int] = None
    # Additional metadata
    rule_id: Optional[str] = None
    fix_suggestion: Optional[str] = None
    cwe_id: Optional[str] = None  # Common Weakness Enumeration

    def to_dict(self) -> dict:
        return asdict(self)


class SecurityCheckRegistry:
    """Registry for security checks with enable/disable support."""

    def __init__(self):
        self._checks: dict[str, SecurityCheck] = {}
        self._categories: set[str] = set()

    def register(
        self,
        name: str,
        category: str,
        description: str,
        check_fn: Callable,
        severity_weight: float = 1.0,
        requires_llm: bool = False,
    ) -> None:
        """Register a security check."""
        self._checks[name] = SecurityCheck(
            name=name,
            category=category,
            description=description,
            check_fn=check_fn,
            severity_weight=severity_weight,
            requires_llm=requires_llm,
        )
        self._categories.add(category)

    def get_check(self, name: str) -> Optional[SecurityCheck]:
        return self._checks.get(name)

    def get_checks_by_category(self, category: str) -> list[SecurityCheck]:
        return [c for c in self._checks.values() if c.category == category and c.enabled]

    def get_all_enabled(self, include_llm: bool = True) -> list[SecurityCheck]:
        """Get all enabled checks, optionally excluding LLM-required ones."""
        checks = [c for c in self._checks.values() if c.enabled]
        if not include_llm:
            checks = [c for c in checks if not c.requires_llm]
        return checks

    def enable(self, name: str) -> bool:
        if name in self._checks:
            self._checks[name].enabled = True
            return True
        return False

    def disable(self, name: str) -> bool:
        if name in self._checks:
            self._checks[name].enabled = False
            return True
        return False

    def enable_category(self, category: str) -> int:
        count = 0
        for check in self._checks.values():
            if check.category == category:
                check.enabled = True
                count += 1
        return count

    def disable_category(self, category: str) -> int:
        count = 0
        for check in self._checks.values():
            if check.category == category:
                check.enabled = False
                count += 1
        return count

    @property
    def categories(self) -> list[str]:
        return sorted(self._categories)

    @property
    def check_names(self) -> list[str]:
        return sorted(self._checks.keys())


# Global registry instance
SECURITY_REGISTRY = SecurityCheckRegistry()


# ============================================================================
# FILE EXCLUSION PATTERNS (respects .gitignore)
# ============================================================================

DEFAULT_EXCLUDE_PATTERNS = {
    # Package managers
    "node_modules/**",
    "vendor/**",
    "bower_components/**",
    # Build artifacts
    "dist/**",
    "build/**",
    "target/**",
    "out/**",
    "*.min.js",
    "*.min.css",
    # Python
    "__pycache__/**",
    "*.pyc",
    ".venv/**",
    "venv/**",
    ".tox/**",
    "*.egg-info/**",
    # IDE/Editor
    ".idea/**",
    ".vscode/**",
    "*.swp",
    "*.swo",
    # Version control
    ".git/**",
    ".svn/**",
    ".hg/**",
    # Coverage/Testing
    "coverage/**",
    ".coverage",
    "htmlcov/**",
    ".pytest_cache/**",
    # Documentation (generated)
    "docs/_build/**",
    "site/**",
}

# Files that should ALWAYS be scanned for secrets (even if in .gitignore)
ALWAYS_SCAN_FOR_SECRETS = {
    ".env",
    ".env.*",
    "*.env",
    ".secrets",
    "secrets.*",
    "credentials.*",
    "*.pem",
    "*.key",
}


def load_gitignore_patterns(cwd: str) -> set[str]:
    """Load patterns from .gitignore file."""
    patterns = set()
    gitignore_path = os.path.join(cwd, ".gitignore")

    if os.path.exists(gitignore_path):
        try:
            with open(gitignore_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if line and not line.startswith("#"):
                        # Convert gitignore pattern to glob pattern
                        if not line.startswith("/"):
                            line = "**/" + line
                        else:
                            line = line[1:]  # Remove leading /
                        if line.endswith("/"):
                            line = line + "**"
                        patterns.add(line)
        except Exception:
            pass

    return patterns


def should_scan_file(
    filepath: str,
    cwd: str,
    exclude_patterns: set[str],
    include_ignored: bool = False,
    for_secrets: bool = False,
) -> bool:
    """Check if a file should be scanned.

    Args:
        filepath: Relative path to the file
        cwd: Working directory
        exclude_patterns: Patterns to exclude
        include_ignored: If True, ignore .gitignore patterns
        for_secrets: If True, always scan files that might contain secrets
    """
    # Always scan certain files for secrets
    if for_secrets:
        basename = os.path.basename(filepath)
        for pattern in ALWAYS_SCAN_FOR_SECRETS:
            if fnmatch.fnmatch(basename, pattern):
                return True

    # Check exclude patterns
    for pattern in exclude_patterns:
        if fnmatch.fnmatch(filepath, pattern):
            if include_ignored:
                continue  # --include-ignored flag overrides
            return False

    return True


def get_scannable_files(
    cwd: str,
    include_ignored: bool = False,
    max_files: int = 0,  # 0 = no limit
    file_extensions: Optional[set[str]] = None,
) -> list[str]:
    """Get list of files to scan, respecting exclusion patterns.

    Args:
        cwd: Working directory
        include_ignored: If True, include files matched by .gitignore
        max_files: Maximum number of files to return (0 = no limit)
        file_extensions: Optional set of extensions to include (e.g., {".py", ".js"})

    Returns:
        List of relative file paths to scan
    """
    # Combine default patterns with .gitignore
    exclude_patterns = DEFAULT_EXCLUDE_PATTERNS.copy()
    if not include_ignored:
        exclude_patterns.update(load_gitignore_patterns(cwd))

    files = []

    for root, dirs, filenames in os.walk(cwd):
        # Filter directories in-place
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {
            "node_modules", "vendor", "__pycache__", "venv", ".venv",
            "dist", "build", "target", ".git"
        }]

        for filename in filenames:
            full_path = os.path.join(root, filename)
            rel_path = os.path.relpath(full_path, cwd)

            # Check extension filter
            if file_extensions:
                ext = os.path.splitext(filename)[1]
                if ext not in file_extensions:
                    continue

            if should_scan_file(rel_path, cwd, exclude_patterns, include_ignored):
                files.append(rel_path)

                # Check max files limit
                if max_files > 0 and len(files) >= max_files:
                    return files

    return files


# ============================================================================
# CODE SNIPPET EXTRACTION
# ============================================================================

def extract_snippet(
    filepath: str,
    line: int,
    context_lines: int = 2,
    max_line_length: int = 120,
) -> tuple[str, int]:
    """Extract code snippet around a line with context.

    Args:
        filepath: Path to the file
        line: 1-indexed line number
        context_lines: Number of lines before and after
        max_line_length: Truncate long lines

    Returns:
        Tuple of (snippet_text, start_line)
    """
    # Validate line number (must be 1-indexed, i.e., >= 1)
    if line < 1:
        return "", 0

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            all_lines = f.readlines()

        # Convert to 0-indexed
        line_idx = line - 1
        start_idx = max(0, line_idx - context_lines)
        end_idx = min(len(all_lines), line_idx + context_lines + 1)

        snippet_lines = []
        for i in range(start_idx, end_idx):
            line_content = all_lines[i].rstrip()
            if len(line_content) > max_line_length:
                line_content = line_content[:max_line_length] + "..."

            # Mark the target line
            marker = ">>> " if i == line_idx else "    "
            snippet_lines.append(f"{i + 1:4d}{marker}{line_content}")

        return "\n".join(snippet_lines), start_idx + 1

    except Exception:
        return "", 0


# ============================================================================
# PATTERN-BASED SECURITY CHECKS (High Confidence)
# ============================================================================

# Secret patterns - these are regex-based with high confidence
SECRET_PATTERNS = [
    # API Keys
    (r'(?i)(api[_-]?key|apikey)\s*[=:]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?', "API key", "CWE-798"),
    (r'(?i)(secret[_-]?key|secretkey)\s*[=:]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?', "Secret key", "CWE-798"),
    (r'(?i)(access[_-]?token|accesstoken)\s*[=:]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?', "Access token", "CWE-798"),

    # AWS
    (r'AKIA[0-9A-Z]{16}', "AWS Access Key ID", "CWE-798"),
    (r'(?i)aws[_-]?secret[_-]?access[_-]?key\s*[=:]\s*["\']?([a-zA-Z0-9/+=]{40})["\']?', "AWS Secret Key", "CWE-798"),

    # Google
    (r'AIza[0-9A-Za-z_-]{35}', "Google API Key", "CWE-798"),

    # GitHub
    (r'ghp_[a-zA-Z0-9]{36}', "GitHub Personal Access Token", "CWE-798"),
    (r'gho_[a-zA-Z0-9]{36}', "GitHub OAuth Token", "CWE-798"),
    (r'ghu_[a-zA-Z0-9]{36}', "GitHub User Token", "CWE-798"),
    (r'ghs_[a-zA-Z0-9]{36}', "GitHub Server Token", "CWE-798"),

    # Private keys
    (r'-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----', "Private key", "CWE-321"),
    (r'-----BEGIN\s+OPENSSH\s+PRIVATE\s+KEY-----', "SSH Private Key", "CWE-321"),

    # Passwords in code
    (r'(?i)(password|passwd|pwd)\s*[=:]\s*["\']([^"\']{8,})["\']', "Hardcoded password", "CWE-798"),

    # Database connection strings
    (r'(?i)(mongodb|mysql|postgres|redis)://[^"\'\s]+:[^"\'\s]+@', "Database credentials in connection string", "CWE-798"),

    # JWT secrets
    (r'(?i)(jwt[_-]?secret|jwt[_-]?key)\s*[=:]\s*["\']?([a-zA-Z0-9_\-]{16,})["\']?', "JWT secret", "CWE-798"),

    # Slack
    (r'xox[baprs]-[0-9]{10,13}-[0-9]{10,13}[a-zA-Z0-9-]*', "Slack Token", "CWE-798"),

    # Stripe
    (r'sk_live_[0-9a-zA-Z]{24,}', "Stripe Live Secret Key", "CWE-798"),
    (r'rk_live_[0-9a-zA-Z]{24,}', "Stripe Live Restricted Key", "CWE-798"),
]

# SQL injection patterns
# Note: These patterns catch common cases but cannot trace data flow.
# A variable assigned from user input then passed to execute() will NOT be caught.
SQL_INJECTION_PATTERNS = [
    # String concatenation in SQL - standard execute methods
    (r'(?i)(execute|cursor\.execute|query|execute_sql|executescript)\s*\(\s*["\'][^"\']*%s', "Possible SQL injection (string formatting)", "CWE-89"),
    (r'(?i)(execute|cursor\.execute|query|execute_sql|db\.execute)\s*\(\s*f["\']', "SQL injection via f-string", "CWE-89"),
    (r'(?i)(execute|cursor\.execute|query|execute_sql)\s*\(\s*["\'][^"\']*\s*\+\s*', "SQL injection via concatenation", "CWE-89"),
    (r'(?i)\.format\s*\([^)]*\)\s*\)', "Possible SQL injection (.format)", "CWE-89"),
    # ORM raw queries - Django, SQLAlchemy, Peewee, etc.
    (r'(?i)\.raw\s*\(\s*f["\']', "SQL injection in ORM raw query (f-string)", "CWE-89"),
    (r'(?i)\.raw\s*\(\s*["\'][^"\']*%', "SQL injection in ORM raw query (% formatting)", "CWE-89"),
    (r'(?i)\.raw\s*\(\s*["\'][^"\']*\s*\+', "SQL injection in ORM raw query (concatenation)", "CWE-89"),
    (r'(?i)RawSQL\s*\(\s*f["\']', "SQL injection via Django RawSQL (f-string)", "CWE-89"),
    (r'(?i)RawSQL\s*\(\s*["\'][^"\']*%', "SQL injection via Django RawSQL (% formatting)", "CWE-89"),
    (r'(?i)text\s*\(\s*f["\']', "SQL injection via SQLAlchemy text() (f-string)", "CWE-89"),
    (r'(?i)\.execute\s*\(\s*text\s*\(\s*f["\']', "SQL injection via SQLAlchemy execute(text(f-string))", "CWE-89"),
    # Additional common patterns
    (r'(?i)connection\.execute\s*\(\s*f["\']', "SQL injection in connection.execute (f-string)", "CWE-89"),
    (r'(?i)session\.execute\s*\(\s*f["\']', "SQL injection in session.execute (f-string)", "CWE-89"),
    # Variable assignment with SQL f-string (query = f"SELECT...")
    (r'(?i)query\s*=\s*f["\']SELECT\s+', "SQL injection via f-string in query variable", "CWE-89"),
    (r'(?i)sql\s*=\s*f["\']SELECT\s+', "SQL injection via f-string in sql variable", "CWE-89"),
]

# XSS patterns
XSS_PATTERNS = [
    # innerHTML without sanitization
    (r'\.innerHTML\s*=\s*[^;]*(?!DOMPurify|sanitize)', "Potential XSS via innerHTML", "CWE-79"),
    # document.write
    (r'document\.write\s*\(', "Potential XSS via document.write", "CWE-79"),
    # eval with user input
    (r'eval\s*\(\s*(?:request|req|params|query|body)', "Code injection via eval", "CWE-94"),
    # dangerouslySetInnerHTML (React)
    (r'dangerouslySetInnerHTML\s*=\s*\{\s*\{\s*__html:\s*[^}]*(?!sanitize|DOMPurify)', "Potential XSS in React", "CWE-79"),
]

# Command injection patterns
COMMAND_INJECTION_PATTERNS = [
    (r'(?i)subprocess\.(run|call|Popen)\s*\([^)]*shell\s*=\s*True', "Command injection risk (shell=True)", "CWE-78"),
    (r'(?i)os\.system\s*\(', "Command injection risk (os.system)", "CWE-78"),
    (r'(?i)exec\s*\(\s*(?:request|req|params|input)', "Code injection via exec", "CWE-94"),
    (r'(?i)child_process\.exec\s*\(', "Command injection risk (child_process.exec)", "CWE-78"),
]

# Path traversal patterns
# Note: The '../' pattern is intentionally specific to file operations to reduce false positives
PATH_TRAVERSAL_PATTERNS = [
    (r'(?i)open\s*\(\s*(?:request|req|params|query|body)', "Potential path traversal", "CWE-22"),
    (r'(?i)(open|read|write|sendFile|readFile|writeFile)\s*\([^)]*\.\./', "Path traversal sequence in file operation", "CWE-22"),
    (r'(?i)sendFile\s*\(\s*(?:request|req|params|query|body)', "Potential path traversal in file serving", "CWE-22"),
]

# Insecure configuration patterns
INSECURE_CONFIG_PATTERNS = [
    (r'(?i)debug\s*[=:]\s*(true|1|yes)', "Debug mode enabled", "CWE-489"),
    (r'(?i)verify\s*=\s*False', "SSL verification disabled", "CWE-295"),
    (r'(?i)ssl[_-]?verify\s*[=:]\s*(false|0|no)', "SSL verification disabled", "CWE-295"),
    (r'(?i)allow[_-]?all[_-]?origins?\s*[=:]\s*(true|1|\*)', "CORS allow all origins", "CWE-942"),
    (r'(?i)csrf[_-]?(protection|enabled)\s*[=:]\s*(false|0|no)', "CSRF protection disabled", "CWE-352"),
]

# Authentication/Authorization patterns
AUTH_PATTERNS = [
    (r'(?i)@login_required\s*\n\s*@admin_required', "Authorization check order may be wrong", "CWE-863"),
    (r'(?i)password\s*==\s*["\'][^"\']+["\']', "Hardcoded password comparison", "CWE-798"),
    (r'(?i)if\s+.*password.*==', "Potential timing attack in password comparison", "CWE-208"),
    (r'(?i)(md5|sha1)\s*\(\s*password', "Weak password hashing algorithm", "CWE-328"),
]


def check_secrets(cwd: str, files: list[str]) -> list[SecurityFinding]:
    """Check for hardcoded secrets and credentials."""
    findings = []

    for filepath in files:
        full_path = os.path.join(cwd, filepath)
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                lines = content.split("\n")
        except Exception:
            continue

        for pattern, description, cwe in SECRET_PATTERNS:
            for match in re.finditer(pattern, content):
                # Find line number
                line_start = content[:match.start()].count("\n") + 1

                snippet, snippet_start = extract_snippet(full_path, line_start)

                findings.append(SecurityFinding(
                    category="secrets",
                    severity="critical",
                    message=f"Potential {description} found",
                    file=filepath,
                    line=line_start,
                    confidence="pattern-matched",
                    snippet=snippet,
                    snippet_start_line=snippet_start,
                    rule_id=f"SEC-SECRETS-{cwe}",
                    cwe_id=cwe,
                    fix_suggestion="Remove hardcoded secret and use environment variables or a secrets manager",
                ))

    return findings


def check_sql_injection(cwd: str, files: list[str]) -> list[SecurityFinding]:
    """Check for SQL injection vulnerabilities."""
    findings = []

    for filepath in files:
        full_path = os.path.join(cwd, filepath)
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            continue

        for pattern, description, cwe in SQL_INJECTION_PATTERNS:
            for match in re.finditer(pattern, content):
                line_start = content[:match.start()].count("\n") + 1
                snippet, snippet_start = extract_snippet(full_path, line_start)

                findings.append(SecurityFinding(
                    category="injection",
                    severity="critical",
                    message=description,
                    file=filepath,
                    line=line_start,
                    confidence="pattern-matched",
                    snippet=snippet,
                    snippet_start_line=snippet_start,
                    rule_id=f"SEC-SQLI-{cwe}",
                    cwe_id=cwe,
                    fix_suggestion="Use parameterized queries or prepared statements",
                ))

    return findings


def check_xss(cwd: str, files: list[str]) -> list[SecurityFinding]:
    """Check for XSS vulnerabilities."""
    findings = []

    for filepath in files:
        full_path = os.path.join(cwd, filepath)
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            continue

        for pattern, description, cwe in XSS_PATTERNS:
            for match in re.finditer(pattern, content):
                line_start = content[:match.start()].count("\n") + 1
                snippet, snippet_start = extract_snippet(full_path, line_start)

                findings.append(SecurityFinding(
                    category="xss",
                    severity="high",
                    message=description,
                    file=filepath,
                    line=line_start,
                    confidence="pattern-matched",
                    snippet=snippet,
                    snippet_start_line=snippet_start,
                    rule_id=f"SEC-XSS-{cwe}",
                    cwe_id=cwe,
                    fix_suggestion="Sanitize user input before rendering or use safe templating",
                ))

    return findings


def check_command_injection(cwd: str, files: list[str]) -> list[SecurityFinding]:
    """Check for command injection vulnerabilities."""
    findings = []

    for filepath in files:
        full_path = os.path.join(cwd, filepath)
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            continue

        for pattern, description, cwe in COMMAND_INJECTION_PATTERNS:
            for match in re.finditer(pattern, content):
                line_start = content[:match.start()].count("\n") + 1
                snippet, snippet_start = extract_snippet(full_path, line_start)

                findings.append(SecurityFinding(
                    category="injection",
                    severity="critical",
                    message=description,
                    file=filepath,
                    line=line_start,
                    confidence="pattern-matched",
                    snippet=snippet,
                    snippet_start_line=snippet_start,
                    rule_id=f"SEC-CMDI-{cwe}",
                    cwe_id=cwe,
                    fix_suggestion="Use subprocess with shell=False and validate/sanitize inputs",
                ))

    return findings


def check_path_traversal(cwd: str, files: list[str]) -> list[SecurityFinding]:
    """Check for path traversal vulnerabilities."""
    findings = []

    for filepath in files:
        full_path = os.path.join(cwd, filepath)
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            continue

        for pattern, description, cwe in PATH_TRAVERSAL_PATTERNS:
            for match in re.finditer(pattern, content):
                line_start = content[:match.start()].count("\n") + 1
                snippet, snippet_start = extract_snippet(full_path, line_start)

                findings.append(SecurityFinding(
                    category="path-traversal",
                    severity="high",
                    message=description,
                    file=filepath,
                    line=line_start,
                    confidence="pattern-matched",
                    snippet=snippet,
                    snippet_start_line=snippet_start,
                    rule_id=f"SEC-PATH-{cwe}",
                    cwe_id=cwe,
                    fix_suggestion="Validate and sanitize file paths, use allowlists",
                ))

    return findings


def check_insecure_config(cwd: str, files: list[str]) -> list[SecurityFinding]:
    """Check for insecure configurations."""
    findings = []

    for filepath in files:
        full_path = os.path.join(cwd, filepath)
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            continue

        for pattern, description, cwe in INSECURE_CONFIG_PATTERNS:
            for match in re.finditer(pattern, content):
                line_start = content[:match.start()].count("\n") + 1
                snippet, snippet_start = extract_snippet(full_path, line_start)

                findings.append(SecurityFinding(
                    category="config",
                    severity="medium",
                    message=description,
                    file=filepath,
                    line=line_start,
                    confidence="pattern-matched",
                    snippet=snippet,
                    snippet_start_line=snippet_start,
                    rule_id=f"SEC-CONFIG-{cwe}",
                    cwe_id=cwe,
                    fix_suggestion="Review and fix security configuration",
                ))

    return findings


def check_auth_issues(cwd: str, files: list[str]) -> list[SecurityFinding]:
    """Check for authentication/authorization issues."""
    findings = []

    for filepath in files:
        full_path = os.path.join(cwd, filepath)
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            continue

        for pattern, description, cwe in AUTH_PATTERNS:
            for match in re.finditer(pattern, content):
                line_start = content[:match.start()].count("\n") + 1
                snippet, snippet_start = extract_snippet(full_path, line_start)

                findings.append(SecurityFinding(
                    category="auth",
                    severity="high",
                    message=description,
                    file=filepath,
                    line=line_start,
                    confidence="pattern-matched",
                    snippet=snippet,
                    snippet_start_line=snippet_start,
                    rule_id=f"SEC-AUTH-{cwe}",
                    cwe_id=cwe,
                    fix_suggestion="Review authentication and authorization logic",
                ))

    return findings


# Register all pattern-based checks
SECURITY_REGISTRY.register(
    name="secrets",
    category="secrets",
    description="Detect hardcoded secrets, API keys, and credentials",
    check_fn=check_secrets,
    severity_weight=1.0,
    requires_llm=False,
)

SECURITY_REGISTRY.register(
    name="sql-injection",
    category="injection",
    description="Detect SQL injection vulnerabilities",
    check_fn=check_sql_injection,
    severity_weight=1.0,
    requires_llm=False,
)

SECURITY_REGISTRY.register(
    name="xss",
    category="xss",
    description="Detect cross-site scripting vulnerabilities",
    check_fn=check_xss,
    severity_weight=0.9,
    requires_llm=False,
)

SECURITY_REGISTRY.register(
    name="command-injection",
    category="injection",
    description="Detect command injection vulnerabilities",
    check_fn=check_command_injection,
    severity_weight=1.0,
    requires_llm=False,
)

SECURITY_REGISTRY.register(
    name="path-traversal",
    category="path-traversal",
    description="Detect path traversal vulnerabilities",
    check_fn=check_path_traversal,
    severity_weight=0.8,
    requires_llm=False,
)

SECURITY_REGISTRY.register(
    name="insecure-config",
    category="config",
    description="Detect insecure configuration settings",
    check_fn=check_insecure_config,
    severity_weight=0.6,
    requires_llm=False,
)

SECURITY_REGISTRY.register(
    name="auth-issues",
    category="auth",
    description="Detect authentication and authorization issues",
    check_fn=check_auth_issues,
    severity_weight=0.9,
    requires_llm=False,
)


# ============================================================================
# AI-POWERED SECURITY ANALYSIS (Lower Confidence)
# ============================================================================

AI_SECURITY_ANALYSIS_PROMPT = """You are a security expert analyzing code for vulnerabilities.

Analyze the following code for security issues. Focus on:
1. Authentication and authorization gaps
2. Data exposure risks
3. OWASP Top 10 vulnerabilities
4. Business logic flaws
5. Insecure data handling

IMPORTANT:
- Only report issues you are confident about
- Do NOT report issues already found by pattern matching
- For each issue, provide the exact file and line number
- Rate each issue's severity: critical, high, medium, low

Already detected issues (do not duplicate):
{existing_findings}

Code to analyze:
{code}

Respond in this exact JSON format:
{{
  "findings": [
    {{
      "category": "auth|data|injection|config|logic",
      "severity": "critical|high|medium|low",
      "message": "Description of the issue",
      "file": "relative/path/to/file.py",
      "line": 42,
      "fix_suggestion": "How to fix this issue"
    }}
  ],
  "analysis_notes": "Any additional observations"
}}

If no new issues are found, return: {{"findings": [], "analysis_notes": "No additional issues found"}}
"""


def truncate_at_function_boundary(content: str, max_chars: int) -> str:
    """Truncate content at a function/class boundary instead of mid-line.

    Tries to find a natural break point (function def, class def, or blank line)
    near the max_chars limit to avoid cutting off in the middle of important code.
    """
    if len(content) <= max_chars:
        return content

    # Look for a good break point in the last 500 chars before the limit
    search_start = max(0, max_chars - 500)
    search_region = content[search_start:max_chars]

    # Try to find function/class boundary (Python, JS, etc.)
    for pattern in ['\ndef ', '\nclass ', '\nfunction ', '\n\n']:
        last_match = search_region.rfind(pattern)
        if last_match != -1:
            cut_point = search_start + last_match
            return content[:cut_point] + f"\n\n... [TRUNCATED at {cut_point} chars, {len(content) - cut_point} chars omitted]"

    # Fall back to line boundary
    last_newline = content[:max_chars].rfind('\n')
    if last_newline > max_chars - 200:
        return content[:last_newline] + f"\n\n... [TRUNCATED at line boundary]"

    # Last resort: hard cut
    return content[:max_chars] + f"\n... [TRUNCATED]"


def run_ai_security_analysis(
    cwd: str,
    files: list[str],
    existing_findings: list[SecurityFinding],
    provider,
    max_files: int = 50,
    batch_size: int = 5,
    max_file_chars: int = 15000,
) -> tuple[list[SecurityFinding], int]:
    """Run AI-powered security analysis on files.

    Args:
        cwd: Working directory
        files: Files to analyze (should already be prioritized by risk)
        existing_findings: Already detected findings (to avoid duplicates)
        provider: LLM provider instance
        max_files: Maximum files to analyze with AI (performance constraint)
        batch_size: Number of files per API call
        max_file_chars: Maximum characters per file (uses semantic truncation)

    Returns:
        Tuple of (list of AI-suggested security findings, total tokens used)
    """
    findings = []
    total_tokens = 0

    # Format existing findings for the prompt
    existing_summary = "\n".join([
        f"- {f.file}:{f.line}: {f.message}"
        for f in existing_findings[:30]  # Limit to avoid token overflow
    ]) or "None"

    files_to_analyze = files[:max_files]  # Enforce max_files limit

    for i in range(0, len(files_to_analyze), batch_size):
        batch = files_to_analyze[i:i + batch_size]

        # Read file contents with semantic truncation
        code_content = []
        for filepath in batch:
            full_path = os.path.join(cwd, filepath)
            try:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    # Use semantic truncation at function boundaries
                    if len(content) > max_file_chars:
                        content = truncate_at_function_boundary(content, max_file_chars)
                    code_content.append(f"=== {filepath} ===\n{content}")
            except Exception:
                continue

        if not code_content:
            continue

        prompt = AI_SECURITY_ANALYSIS_PROMPT.format(
            existing_findings=existing_summary,
            code="\n\n".join(code_content),
        )

        try:
            # Use the provider's ask method for analysis
            result = provider.ask(prompt, "", cwd)

            if not result.success or not result.content:
                continue

            # Track tokens used if available
            if hasattr(result, 'tokens_used') and result.tokens_used:
                total_tokens += result.tokens_used
            elif hasattr(result, 'usage') and result.usage:
                total_tokens += getattr(result.usage, 'total_tokens', 0)

            # Parse JSON response
            try:
                # Extract JSON from response (handle markdown code blocks)
                content = result.content
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]

                data = json.loads(content.strip())

                for finding_data in data.get("findings", []):
                    # Add AI-suggested finding with lower confidence
                    filepath = finding_data.get("file", "")
                    line = finding_data.get("line")

                    snippet = ""
                    snippet_start = 0
                    if filepath and line:
                        full_path = os.path.join(cwd, filepath)
                        if os.path.exists(full_path):
                            snippet, snippet_start = extract_snippet(full_path, line)

                    findings.append(SecurityFinding(
                        category=finding_data.get("category", "unknown"),
                        severity=finding_data.get("severity", "medium"),
                        message=finding_data.get("message", ""),
                        file=filepath,
                        line=line,
                        confidence="ai-suggested",  # Mark as AI-suggested (lower confidence)
                        snippet=snippet,
                        snippet_start_line=snippet_start,
                        fix_suggestion=finding_data.get("fix_suggestion"),
                    ))

            except json.JSONDecodeError:
                # AI response wasn't valid JSON, skip
                continue

        except Exception as e:
            # Log error but continue with other batches
            Display.notify(f"AI analysis error: {str(e)[:50]}")
            continue

    return findings, total_tokens


# ============================================================================
# AUDIT TRAIL LOGGING
# ============================================================================

@dataclass
class AuditLogEntry:
    """Entry in the audit trail for security changes."""
    timestamp: float
    action: str  # "scan", "finding", "fix_proposed", "fix_applied", "fix_rejected"
    user: str
    file: Optional[str] = None
    finding_id: Optional[str] = None
    details: Optional[str] = None
    diff: Optional[str] = None
    confirmed: bool = False


class AuditTrail:
    """Audit trail for security operations with history and diff support."""

    def __init__(self, cwd: str):
        self.cwd = cwd
        self.log_dir = os.path.join(cwd, ".lion", "audit")
        os.makedirs(self.log_dir, exist_ok=True)
        self.log_file = os.path.join(
            self.log_dir,
            f"audit_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
        )

    def log(self, entry: AuditLogEntry) -> None:
        """Write an entry to the audit log."""
        with open(self.log_file, "a") as f:
            f.write(json.dumps(asdict(entry)) + "\n")

    def log_scan_start(self, files_count: int, checks_enabled: list[str]) -> None:
        self.log(AuditLogEntry(
            timestamp=time.time(),
            action="scan_start",
            user=os.environ.get("USER", "unknown"),
            details=f"Scanning {files_count} files with checks: {', '.join(checks_enabled)}",
        ))

    def log_finding(self, finding: SecurityFinding) -> None:
        self.log(AuditLogEntry(
            timestamp=time.time(),
            action="finding",
            user=os.environ.get("USER", "unknown"),
            file=finding.file,
            finding_id=f"{finding.file}:{finding.line}:{finding.rule_id}",
            details=f"[{finding.confidence}] {finding.severity}: {finding.message}",
        ))

    def log_fix_proposed(self, finding: SecurityFinding, diff: str) -> None:
        self.log(AuditLogEntry(
            timestamp=time.time(),
            action="fix_proposed",
            user=os.environ.get("USER", "unknown"),
            file=finding.file,
            finding_id=f"{finding.file}:{finding.line}:{finding.rule_id}",
            diff=diff,
            confirmed=False,
        ))

    def log_fix_applied(self, finding: SecurityFinding, confirmed: bool) -> None:
        self.log(AuditLogEntry(
            timestamp=time.time(),
            action="fix_applied",
            user=os.environ.get("USER", "unknown"),
            file=finding.file,
            finding_id=f"{finding.file}:{finding.line}:{finding.rule_id}",
            confirmed=confirmed,
        ))

    def get_history(self, max_entries: int = 10) -> list[dict]:
        """Get list of previous audit runs with summary info.

        Returns list of dicts with: timestamp, log_file, findings_count, severities
        """
        import glob as glob_module

        history = []
        log_files = sorted(
            glob_module.glob(os.path.join(self.log_dir, "audit_*.jsonl")),
            reverse=True
        )[:max_entries]

        for log_file in log_files:
            try:
                findings_count = 0
                severities = {}
                scan_time = None

                with open(log_file, "r") as f:
                    for line in f:
                        entry = json.loads(line)
                        if entry.get("action") == "scan_start":
                            scan_time = entry.get("timestamp")
                        elif entry.get("action") == "finding":
                            findings_count += 1
                            details = entry.get("details", "")
                            for sev in ["critical", "high", "medium", "low", "info"]:
                                if sev in details.lower():
                                    severities[sev] = severities.get(sev, 0) + 1
                                    break

                history.append({
                    "timestamp": scan_time,
                    "log_file": log_file,
                    "findings_count": findings_count,
                    "severities": severities,
                })
            except Exception:
                continue

        return history

    def get_diff_from_last(self, current_findings: list[SecurityFinding]) -> dict:
        """Compare current findings with last scan.

        Returns dict with: new_findings, resolved_findings, unchanged_count
        """
        import glob as glob_module

        # Find the previous log file (not the current one)
        log_files = sorted(
            glob_module.glob(os.path.join(self.log_dir, "audit_*.jsonl")),
            reverse=True
        )

        # Skip the current log file
        previous_log = None
        for lf in log_files:
            if lf != self.log_file:
                previous_log = lf
                break

        if not previous_log:
            return {
                "new_findings": [f.to_dict() for f in current_findings],
                "resolved_findings": [],
                "unchanged_count": 0,
                "previous_scan": None,
            }

        # Load previous findings
        previous_finding_ids = set()
        try:
            with open(previous_log, "r") as f:
                for line in f:
                    entry = json.loads(line)
                    if entry.get("action") == "finding":
                        finding_id = entry.get("finding_id", "")
                        previous_finding_ids.add(finding_id)
        except Exception:
            pass

        # Current finding IDs
        current_finding_ids = {
            f"{f.file}:{f.line}:{f.rule_id}" for f in current_findings
        }

        # Calculate diff
        new_ids = current_finding_ids - previous_finding_ids
        resolved_ids = previous_finding_ids - current_finding_ids
        unchanged_count = len(current_finding_ids & previous_finding_ids)

        new_findings = [
            f.to_dict() for f in current_findings
            if f"{f.file}:{f.line}:{f.rule_id}" in new_ids
        ]

        return {
            "new_findings": new_findings,
            "resolved_findings": list(resolved_ids),
            "unchanged_count": unchanged_count,
            "previous_scan": previous_log,
        }


# ============================================================================
# FILE CHANGE TRACKING (for deduplication with related file inclusion)
# ============================================================================

def get_file_hash(filepath: str) -> str:
    """Get hash of file contents for change detection.

    Uses SHA256 for collision resistance (consistent with security focus of this module).
    """
    try:
        with open(filepath, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return ""


def load_file_hashes(cache_path: str) -> dict[str, str]:
    """Load cached file hashes."""
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_file_hashes(cache_path: str, hashes: dict[str, str]) -> None:
    """Save file hashes to cache."""
    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(hashes, f)
    except Exception:
        pass


def get_file_imports(filepath: str, cwd: str, filter_existing: bool = False) -> set[str]:
    """Extract import statements from a file to find related files.

    Args:
        filepath: Relative path to the file
        cwd: Working directory
        filter_existing: If True, only return imports that exist on disk

    Returns set of relative file paths that this file imports.
    """
    imports = set()
    full_path = os.path.join(cwd, filepath)

    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Python imports
        if filepath.endswith(".py"):
            # from x.y.z import ... -> x/y/z.py or x/y/z/__init__.py
            for match in re.finditer(r'^\s*from\s+([\w.]+)\s+import', content, re.MULTILINE):
                module = match.group(1).replace(".", "/")
                imports.add(f"{module}.py")
                imports.add(f"{module}/__init__.py")
            # import x.y.z
            for match in re.finditer(r'^\s*import\s+([\w.]+)', content, re.MULTILINE):
                module = match.group(1).replace(".", "/")
                imports.add(f"{module}.py")

        # JavaScript/TypeScript imports
        elif filepath.endswith((".js", ".ts", ".jsx", ".tsx")):
            # ES6 imports: import ... from './path' or import ... from "path"
            for match in re.finditer(r'from\s+[\'"]([^"\']+)[\'"]', content):
                imp = match.group(1)
                if imp.startswith("."):
                    # Resolve relative path
                    base_dir = os.path.dirname(filepath)
                    resolved = os.path.normpath(os.path.join(base_dir, imp))
                    for ext in ["", ".js", ".ts", ".jsx", ".tsx", "/index.js", "/index.ts"]:
                        imports.add(resolved + ext)
            # CommonJS require('./path')
            for match in re.finditer(r'require\s*\([\'"]([^"\']+)[\'"]\)', content):
                imp = match.group(1)
                if imp.startswith("."):
                    # Resolve relative path
                    base_dir = os.path.dirname(filepath)
                    resolved = os.path.normpath(os.path.join(base_dir, imp))
                    for ext in ["", ".js", ".ts", ".jsx", ".tsx", "/index.js", "/index.ts"]:
                        imports.add(resolved + ext)

    except Exception:
        pass

    # Filter to only existing files if requested
    if filter_existing:
        return {imp for imp in imports if os.path.exists(os.path.join(cwd, imp))}
    return imports


def get_changed_files(
    cwd: str,
    files: list[str],
    cache_path: str,
    include_related: bool = True,
) -> tuple[list[str], dict[str, str]]:
    """Get files that have changed since last scan, plus related files.

    When include_related=True, also includes files that import or are imported
    by changed files. This catches vulnerabilities that span multiple files.

    Note: Deduplication is for performance only. Users should do periodic
    full scans (--full) to catch all cross-file vulnerabilities.

    Returns:
        Tuple of (changed_files, new_hashes)
    """
    old_hashes = load_file_hashes(cache_path)
    new_hashes = {}
    changed = []

    for filepath in files:
        full_path = os.path.join(cwd, filepath)
        new_hash = get_file_hash(full_path)
        new_hashes[filepath] = new_hash

        if old_hashes.get(filepath) != new_hash:
            changed.append(filepath)

    # Include files that import changed files or are imported by them
    if include_related and changed:
        related = set()
        changed_set = set(changed)

        for filepath in files:
            if filepath in changed_set:
                # Add files that this changed file imports
                imports = get_file_imports(filepath, cwd)
                for imp in imports:
                    if imp in new_hashes and imp not in changed_set:
                        related.add(imp)
            else:
                # Check if this file imports any changed file
                imports = get_file_imports(filepath, cwd)
                for imp in imports:
                    if imp in changed_set:
                        related.add(filepath)
                        break

        # Add related files to changed list
        changed.extend(list(related))

    return changed, new_hashes


def prioritize_files_for_ai(
    files: list[str],
    high_risk_paths: list[str],
    max_files: int,
) -> list[str]:
    """Prioritize files for AI analysis based on risk.

    High-risk paths (auth, payment, etc.) are analyzed first.
    Returns up to max_files prioritized by risk.
    """
    high_risk = []
    normal = []

    for filepath in files:
        is_high_risk = False
        for pattern in high_risk_paths:
            if fnmatch.fnmatch(filepath, pattern):
                is_high_risk = True
                break

        if is_high_risk:
            high_risk.append(filepath)
        else:
            normal.append(filepath)

    # Combine: high-risk first, then normal
    prioritized = high_risk + normal
    return prioritized[:max_files]


# ============================================================================
# LOW-RISK SELF-HEAL FIXES
# ============================================================================

# These are the ONLY patterns that can be auto-fixed with self-heal (^)
# Complex security issues like SQL injection require manual review

SELF_HEAL_FIXES = {
    # secrets_to_env: Replace hardcoded secrets with os.environ.get()
    "secrets_to_env": {
        "category": "secrets",
        "description": "Replace hardcoded secret with environment variable",
        "patterns": [
            # API_KEY = "hardcoded_value" -> API_KEY = os.environ.get("API_KEY")
            (
                r'(?P<varname>[A-Z_]+(?:KEY|SECRET|TOKEN|PASSWORD))\s*=\s*["\']([^"\']{8,})["\']',
                lambda m: f'{m.group("varname")} = os.environ.get("{m.group("varname")}")',
            ),
        ],
    },
    # debug_false: Set DEBUG = False
    "debug_false": {
        "category": "config",
        "description": "Disable debug mode",
        "patterns": [
            (r'(?i)(DEBUG|debug)\s*=\s*(True|1|"true"|\'true\')', r'\1 = False'),
        ],
    },
    # ssl_verify_true: Set verify = True
    "ssl_verify_true": {
        "category": "config",
        "description": "Enable SSL verification",
        "patterns": [
            (r'verify\s*=\s*False', 'verify = True'),
            (r'(?i)ssl[_-]?verify\s*=\s*(false|0|"false"|\'false\')', 'ssl_verify = True'),
        ],
    },
}


def generate_self_heal_fix(
    finding: SecurityFinding,
    cwd: str,
    allowed_rules: list[str],
) -> Optional[tuple[str, str, str]]:
    """Generate a fix for a finding if it matches a safe self-heal rule.

    Args:
        finding: The security finding
        cwd: Working directory
        allowed_rules: List of allowed self-heal rule names from config

    Returns:
        Tuple of (original_line, fixed_line, rule_name) or None if no safe fix
    """
    if not finding.snippet or finding.line is None:
        return None

    # Only fix pattern-matched findings (not AI suggestions)
    if finding.confidence != "pattern-matched":
        return None

    for rule_name, rule_config in SELF_HEAL_FIXES.items():
        if rule_name not in allowed_rules:
            continue

        if finding.category != rule_config["category"]:
            continue

        # Read the actual line from file
        full_path = os.path.join(cwd, finding.file)
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                if finding.line <= len(lines):
                    original_line = lines[finding.line - 1]

                    # Try each pattern
                    for pattern, replacement in rule_config["patterns"]:
                        if re.search(pattern, original_line):
                            if callable(replacement):
                                fixed_line = re.sub(pattern, replacement, original_line)
                            else:
                                fixed_line = re.sub(pattern, replacement, original_line)

                            if fixed_line != original_line:
                                return (original_line.rstrip(), fixed_line.rstrip(), rule_name)
        except Exception:
            pass

    return None


def _ensure_os_import(lines: list[str], filepath: str) -> tuple[list[str], bool]:
    """Ensure 'import os' exists in file if os.environ is used.

    Returns tuple of (modified_lines, was_import_added).
    """
    content = "".join(lines)

    # Check if os is already imported
    if re.search(r'^import\s+os\b', content, re.MULTILINE):
        return lines, False
    if re.search(r'^from\s+os\s+import', content, re.MULTILINE):
        return lines, False

    # Find the right place to add the import
    # Look for existing imports or module docstring
    insert_line = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Skip docstrings, comments, and blank lines at the start
        if stripped.startswith('"""') or stripped.startswith("'''"):
            # Find end of docstring
            if stripped.count('"""') == 1 or stripped.count("'''") == 1:
                quote = '"""' if '"""' in stripped else "'''"
                found_closing = False
                for j in range(i + 1, len(lines)):
                    if quote in lines[j]:
                        insert_line = j + 1
                        found_closing = True
                        break
                # Handle unclosed docstring - insert after current line
                if not found_closing:
                    insert_line = i + 1
            else:
                insert_line = i + 1
        elif stripped.startswith('#') or not stripped:
            continue
        elif stripped.startswith('import ') or stripped.startswith('from '):
            insert_line = i
            break
        else:
            insert_line = i
            break

    # Insert the import
    lines.insert(insert_line, "import os\n")
    return lines, True


def apply_self_heal_fixes(
    findings: list[SecurityFinding],
    cwd: str,
    allowed_rules: list[str],
    audit_trail: AuditTrail,
) -> list[dict]:
    """Apply safe self-heal fixes to findings.

    Only applies fixes for low-risk categories as defined in SELF_HEAL_FIXES.
    All fixes are logged to the audit trail.

    Returns list of applied fixes with details.
    """
    applied = []

    # Group findings by file for efficient editing
    by_file: dict[str, list[tuple[SecurityFinding, tuple]]] = {}

    for finding in findings:
        fix = generate_self_heal_fix(finding, cwd, allowed_rules)
        if fix:
            if finding.file not in by_file:
                by_file[finding.file] = []
            by_file[finding.file].append((finding, fix))

    # Apply fixes file by file
    for filepath, fixes in by_file.items():
        full_path = os.path.join(cwd, filepath)

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # Check if any fix uses os.environ (secrets_to_env) and ensure import exists
            needs_os_import = any(
                rule_name == "secrets_to_env" for _, (_, _, rule_name) in fixes
            )
            import_added = False
            if needs_os_import and filepath.endswith('.py'):
                lines, import_added = _ensure_os_import(lines, filepath)

            # Apply fixes in reverse line order to preserve line numbers
            fixes.sort(key=lambda x: x[0].line or 0, reverse=True)

            for finding, (original, fixed, rule_name) in fixes:
                # Adjust line number if import was added at the top
                target_line = finding.line
                if import_added and finding.line:
                    target_line = finding.line + 1

                if target_line and target_line <= len(lines):
                    # Log the fix proposal
                    diff = f"-{original}\n+{fixed}"
                    audit_trail.log_fix_proposed(finding, diff)

                    # Apply the fix
                    lines[target_line - 1] = fixed + "\n"

                    # Log the applied fix
                    audit_trail.log_fix_applied(finding, confirmed=True)

                    applied.append({
                        "file": filepath,
                        "line": finding.line,  # Report original line number
                        "rule": rule_name,
                        "original": original,
                        "fixed": fixed,
                        "import_added": import_added if rule_name == "secrets_to_env" else False,
                    })

            # Write the modified file
            with open(full_path, "w", encoding="utf-8") as f:
                f.writelines(lines)

        except Exception as e:
            # Log error but continue with other files
            Display.step_error("audit", f"Failed to apply fixes to {filepath}: {str(e)[:50]}")
            continue

    return applied


# ============================================================================
# MAIN AUDIT FUNCTION
# ============================================================================

def execute_audit(prompt, previous, step, memory, config, cwd, cost_manager=None) -> dict:  # noqa: C901
    """Execute security scan with pattern-based and optional AI analysis.

    IMPORTANT SAFETY FEATURES:
    1. Self-heal (^) only applies LOW-RISK fixes (secrets→env, debug→false, SSL→true)
    2. Complex security issues (SQL injection, auth) require manual review
    3. All AI-suggested findings are marked with confidence: "ai-suggested"
    4. All operations are logged to audit trail
    5. Respects .gitignore by default

    COVERAGE LIMITATIONS:
    - Checks ~40 common patterns; cannot trace data flow or detect indirect vulns
    - Use with bandit, semgrep, or commercial SAST for comprehensive coverage

    Args:
        prompt: The original user prompt
        previous: Dict with output from previous steps
        step: The PipelineStep with function name and args
        memory: SharedMemory instance for logging
        config: Lion configuration dict
        cwd: Working directory
        cost_manager: Optional cost tracking manager

    Arguments (via step.args):
        --quick: Run pattern-only scan (no AI analysis)
        --full: Force full scan (ignore change deduplication)
        --include-ignored: Include files matched by .gitignore
        --max-files N: Limit number of files to scan
        --category CAT: Only run checks from specific category
        --disable CHECK: Disable specific check by name
        --history: Show audit history instead of scanning
        --diff: Show diff from last scan

    Self-heal (^): Enabled for LOW-RISK categories only:
        - secrets: Replace hardcoded values with os.environ.get()
        - config (debug): Set DEBUG = False
        - config (ssl): Set verify = True

    Returns:
        dict with success, findings, stats, etc.
    """
    previous = previous or {}

    # Get audit config from config.toml
    audit_config = config.get("audit", {})
    max_ai_files = audit_config.get("max_ai_files", 50)
    ai_batch_size = audit_config.get("ai_batch_size", 5)
    max_file_chars = audit_config.get("max_file_chars", 15000)
    high_risk_paths = audit_config.get("high_risk_paths", [
        "**/auth/**", "**/authentication/**", "**/login/**",
        "**/payment/**", "**/billing/**", "**/checkout/**",
        "**/admin/**", "**/api/**", "**/security/**",
    ])
    self_heal_rules = audit_config.get("self_heal_rules", [
        "secrets_to_env", "debug_false", "ssl_verify_true"
    ])

    # Parse arguments
    quick_mode = False
    full_scan = False
    include_ignored = False
    max_files = 0  # 0 = no limit for pattern matching
    category_filter = None
    disabled_checks = set()
    show_history = False
    show_diff = False
    self_heal = getattr(step, 'self_heal', False)
    confirm_fixes = False  # Never auto-fix without explicit --confirm

    if step.args:
        i = 0
        while i < len(step.args):
            arg = str(step.args[i]).lower()
            if arg == "--quick" or arg == "quick":
                quick_mode = True
            elif arg == "--full" or arg == "full":
                full_scan = True
            elif arg == "--include-ignored" or arg == "include-ignored":
                include_ignored = True
            elif arg == "--history" or arg == "history":
                show_history = True
            elif arg == "--diff" or arg == "diff":
                show_diff = True
            elif arg == "--max-files" and i + 1 < len(step.args):
                try:
                    max_files = int(step.args[i + 1])
                    i += 1
                except ValueError:
                    pass
            elif arg == "--category" and i + 1 < len(step.args):
                category_filter = str(step.args[i + 1]).lower()
                i += 1
            elif arg == "--disable" and i + 1 < len(step.args):
                disabled_checks.add(str(step.args[i + 1]).lower())
                i += 1
            i += 1

    # Initialize audit trail
    audit_trail = AuditTrail(cwd)

    # Handle --history mode
    if show_history:
        Display.phase("audit", "Showing audit history...")
        history = audit_trail.get_history(max_entries=10)
        return {
            "success": True,
            "mode": "history",
            "history": history,
            "history_count": len(history),
            # Include standard fields for consistent pipeline interface
            "files_changed": [],
            "tokens_used": 0,
            "findings": [],
            "findings_count": 0,
        }

    Display.phase("audit", "Running security scan...")

    # Get enabled checks (using local disabled_checks set instead of mutating global registry)
    # This avoids persistent state mutation across multiple execute_audit calls
    all_checks = SECURITY_REGISTRY.get_all_enabled(include_llm=not quick_mode)
    enabled_checks = [c for c in all_checks if c.name not in disabled_checks]
    if category_filter:
        enabled_checks = [c for c in enabled_checks if c.category == category_filter]

    Display.notify(f"Enabled checks: {', '.join(c.name for c in enabled_checks)}")

    # Get files to scan
    start = time.time()
    files = get_scannable_files(
        cwd,
        include_ignored=include_ignored,
        max_files=max_files,
    )

    Display.notify(f"Scanning {len(files)} files...")

    # Log scan start
    audit_trail.log_scan_start(len(files), [c.name for c in enabled_checks])

    # Check for file changes (deduplication for AI analysis)
    # Includes related files (imports/dependencies) to catch cross-file vulns
    cache_path = os.path.join(cwd, ".lion", "audit", "file_hashes.json")
    if full_scan:
        # --full flag: analyze all files, ignore deduplication
        changed_files = files
        new_hashes = {f: get_file_hash(os.path.join(cwd, f)) for f in files}
        Display.notify("Full scan mode: analyzing all files")
    else:
        changed_files, new_hashes = get_changed_files(cwd, files, cache_path, include_related=True)
        if changed_files and len(changed_files) < len(files):
            Display.notify(f"Deduplication: {len(changed_files)} changed/related files for AI analysis")
            Display.notify("(Use --full for complete scan of all files)")

    # Run pattern-based checks (always runs on ALL files, high confidence)
    all_findings: list[SecurityFinding] = []
    pattern_checks = [c for c in enabled_checks if not c.requires_llm]

    for check in pattern_checks:
        Display.notify(f"Running check: {check.name}")
        try:
            findings = check.check_fn(cwd, files)
            all_findings.extend(findings)
        except Exception as e:
            Display.step_error("audit", f"Check {check.name} failed: {str(e)[:50]}")

    pattern_findings_count = len(all_findings)
    Display.notify(f"Pattern checks found {pattern_findings_count} issues")

    # Run AI analysis if not in quick mode and provider available
    ai_findings_count = 0
    llm_available = True
    llm_error = None
    total_tokens = 0
    files_not_analyzed = 0

    if not quick_mode:
        try:
            default_provider_name = config.get("providers", {}).get("default", "claude")
            provider = get_provider(default_provider_name, config)

            # Prioritize high-risk files for AI analysis
            files_for_ai = changed_files if changed_files else files
            files_for_ai = prioritize_files_for_ai(files_for_ai, high_risk_paths, max_ai_files)

            # Track how many files we couldn't analyze
            files_not_analyzed = max(0, len(changed_files) - max_ai_files) if changed_files else 0

            if files_for_ai:
                Display.notify(f"Running AI analysis on {len(files_for_ai)} files (prioritized by risk)...")
                if files_not_analyzed > 0:
                    Display.notify(f"  Note: {files_not_analyzed} additional files not analyzed (max_ai_files={max_ai_files})")

                ai_findings, tokens_from_ai = run_ai_security_analysis(
                    cwd,
                    files_for_ai,
                    all_findings,
                    provider,
                    max_files=max_ai_files,
                    batch_size=ai_batch_size,
                    max_file_chars=max_file_chars,
                )
                all_findings.extend(ai_findings)
                ai_findings_count = len(ai_findings)
                total_tokens += tokens_from_ai
                Display.notify(f"AI analysis found {ai_findings_count} additional issues")

                # Update file hash cache after successful AI scan
                save_file_hashes(cache_path, new_hashes)
            else:
                Display.notify("No changed files to analyze with AI")

        except Exception as e:
            # Fallback: continue with pattern-only results
            llm_available = False
            llm_error = str(e)
            Display.notify(f"AI analysis unavailable: {llm_error[:50]}. Continuing with pattern-only scan.")

    duration = time.time() - start

    # Log all findings to audit trail
    for finding in all_findings:
        audit_trail.log_finding(finding)

    # Sort findings by severity
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    all_findings.sort(key=lambda f: (severity_order.get(f.severity, 5), f.file, f.line or 0))

    # Count by severity
    severity_counts = {}
    for finding in all_findings:
        severity_counts[finding.severity] = severity_counts.get(finding.severity, 0) + 1

    # Count by confidence
    confidence_counts = {}
    for finding in all_findings:
        confidence_counts[finding.confidence] = confidence_counts.get(finding.confidence, 0) + 1

    # Apply self-heal fixes if enabled (^ operator)
    # Only applies LOW-RISK fixes as defined in SELF_HEAL_FIXES
    applied_fixes = []
    if self_heal and all_findings:
        Display.notify("Self-heal mode: applying LOW-RISK fixes only...")
        applied_fixes = apply_self_heal_fixes(
            all_findings,
            cwd,
            self_heal_rules,
            audit_trail,
        )
        if applied_fixes:
            Display.notify(f"Applied {len(applied_fixes)} safe fixes:")
            for fix in applied_fixes:
                Display.notify(f"  - {fix['file']}:{fix['line']} ({fix['rule']})")
        else:
            Display.notify("No safe auto-fixes available for found issues")
            Display.notify("Complex security issues (SQL injection, auth, etc.) require manual review")

    # Calculate diff from previous scan if requested
    diff_info = None
    if show_diff:
        diff_info = audit_trail.get_diff_from_last(all_findings)
        if diff_info.get("previous_scan"):
            new_count = len(diff_info.get("new_findings", []))
            resolved_count = len(diff_info.get("resolved_findings", []))
            unchanged = diff_info.get("unchanged_count", 0)
            Display.notify(f"Diff from last scan: +{new_count} new, -{resolved_count} resolved, {unchanged} unchanged")

    # Log to memory
    memory.write(MemoryEntry(
        timestamp=time.time(),
        phase="audit",
        agent="security_scanner",
        type="audit_run",
        content=f"Found {len(all_findings)} security issues",
        metadata={
            "files_scanned": len(files),
            "findings_count": len(all_findings),
            "pattern_findings": pattern_findings_count,
            "ai_findings": ai_findings_count,
            "severity_counts": severity_counts,
            "confidence_counts": confidence_counts,
            "quick_mode": quick_mode,
            "full_scan": full_scan,
            "llm_available": llm_available,
            "duration": duration,
            "self_heal": self_heal,
            "fixes_applied": len(applied_fixes),
        },
    ))

    # Prepare output
    result = {
        "success": True,
        "findings": [f.to_dict() for f in all_findings],
        "findings_count": len(all_findings),
        "severity_counts": severity_counts,
        "confidence_counts": confidence_counts,
        "files_scanned": len(files),
        "files_not_analyzed": files_not_analyzed,
        "pattern_findings": pattern_findings_count,
        "ai_findings": ai_findings_count,
        "quick_mode": quick_mode,
        "full_scan": full_scan,
        "llm_available": llm_available,
        "llm_error": llm_error,
        "duration": duration,
        "audit_log": audit_trail.log_file,
        "files_changed": previous.get("files_changed", []),
        "tokens_used": total_tokens,
        # Self-heal results
        "self_heal_enabled": self_heal,
        "fixes_applied": applied_fixes,
        # Diff info (if requested)
        "diff": diff_info,
    }

    # Security notice
    if all_findings:
        critical_count = severity_counts.get("critical", 0)
        high_count = severity_counts.get("high", 0)
        ai_suggested_count = confidence_counts.get("ai-suggested", 0)

        Display.notify(f"Found {len(all_findings)} security issues")
        if critical_count > 0:
            Display.step_error("audit", f"  - {critical_count} CRITICAL")  # Use step_error for critical issues
        if high_count > 0:
            Display.notify(f"  - {high_count} HIGH")  # Use notify for non-error severity counts
        if ai_suggested_count > 0:
            Display.notify(f"  Note: {ai_suggested_count} findings are AI-suggested and require human validation")

        # Self-heal guidance
        if not self_heal and applied_fixes == []:
            fixable = sum(1 for f in all_findings if f.category in ["secrets", "config"])
            if fixable > 0:
                Display.notify(f"  Tip: {fixable} issues may be auto-fixable with self-heal (^audit)")
    else:
        Display.notify("No security issues found")

    # Warning about AI findings
    if ai_findings_count > 0:
        Display.notify(
            "WARNING: AI-suggested findings (confidence: ai-suggested) require human validation. "
            "These may contain false positives."
        )

    # Coverage warning
    if files_not_analyzed > 0:
        Display.notify(
            f"COVERAGE: {files_not_analyzed} files exceeded AI analysis budget. "
            f"Increase [audit].max_ai_files in config.toml for more coverage."
        )

    # Disclaimer - updated to be more honest about limitations
    Display.notify(
        "IMPORTANT: This scan checks ~40 common patterns but cannot trace data flow "
        "or detect indirect vulnerabilities. Use with bandit/semgrep for comprehensive coverage."
    )

    return result

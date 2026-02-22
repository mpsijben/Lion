"""migrate() - Migration Planning Assistant

IMPORTANT: This function does NOT generate "zero-downtime migration plans."

Static file analysis CANNOT:
- Verify runtime dependencies and actual system behavior
- Understand specific failure modes of your stack
- Guarantee rollback procedures work with your state management
- Know if your database supports multi-writer for blue-green deployments

Instead, this function generates:
1. A MIGRATION ASSESSMENT QUESTIONNAIRE - questions you must answer before migrating
2. DETECTED CHANGES requiring migration (schema, config, dependencies)
3. A CHECKLIST OF CONSIDERATIONS with "VERIFY THIS ASSUMPTION" callouts
4. LINKS TO RELEVANT DOCUMENTATION for your detected tech stack

The user answers the questions, verifies the assumptions, and then creates their
actual migration plan using this assessment as input.
"""

import json
import os
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Optional
from enum import Enum

from ..memory import MemoryEntry
from ..display import Display
from ..providers import get_provider
from .utils import detect_project_language


# ============================================================================
# DATA STRUCTURES
# ============================================================================

class ChangeType(str, Enum):
    SCHEMA = "schema"
    CONFIG = "config"
    DEPENDENCY = "dependency"
    API = "api"
    INFRASTRUCTURE = "infrastructure"
    CODE = "code"


class MigrationRisk(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


@dataclass
class DetectedChange:
    """A detected change that may require migration."""
    change_type: ChangeType
    description: str
    file: str
    risk: MigrationRisk
    confidence: str  # "detected" (from diff) or "inferred" (from analysis)
    questions: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    considerations: list[str] = field(default_factory=list)
    documentation_links: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "change_type": self.change_type.value,
            "description": self.description,
            "file": self.file,
            "risk": self.risk.value,
            "confidence": self.confidence,
            "questions": self.questions,
            "assumptions": self.assumptions,
            "considerations": self.considerations,
            "documentation_links": self.documentation_links,
        }


@dataclass
class MigrationQuestion:
    """A question that must be answered before migration can be planned."""
    question: str
    category: str  # state, deployment, rollback, data, dependencies
    why_it_matters: str
    default_assumption: Optional[str] = None
    options: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MigrationAssessment:
    """Structured migration assessment output."""
    detected_changes: list[DetectedChange] = field(default_factory=list)
    questions: list[MigrationQuestion] = field(default_factory=list)
    general_considerations: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    tech_stack_detected: list[str] = field(default_factory=list)
    documentation_links: list[str] = field(default_factory=list)
    confidence_summary: str = ""

    def to_dict(self) -> dict:
        return {
            "detected_changes": [c.to_dict() for c in self.detected_changes],
            "questions": [q.to_dict() for q in self.questions],
            "general_considerations": self.general_considerations,
            "assumptions": self.assumptions,
            "warnings": self.warnings,
            "next_steps": self.next_steps,
            "tech_stack_detected": self.tech_stack_detected,
            "documentation_links": self.documentation_links,
            "confidence_summary": self.confidence_summary,
        }

    def to_markdown(self) -> str:
        """Render assessment as markdown for display."""
        lines = []

        # Header with prominent warning
        lines.append("## Migration Planning Assessment")
        lines.append("")
        lines.append("> **This is NOT a migration plan.** This is an assessment to help you")
        lines.append("> create YOUR migration plan. Static analysis cannot verify runtime")
        lines.append("> behavior, rollback safety, or your specific deployment constraints.")
        lines.append(">")
        lines.append("> **Answer the questions below**, **verify all assumptions**, and then")
        lines.append("> create your actual migration plan based on this assessment.")
        lines.append("")

        # Confidence summary
        if self.confidence_summary:
            lines.append(f"**Assessment Confidence**: {self.confidence_summary}")
            lines.append("")

        # Warnings
        if self.warnings:
            lines.append("### Warnings")
            for warning in self.warnings:
                lines.append(f"- {warning}")
            lines.append("")

        # Tech stack detected
        if self.tech_stack_detected:
            lines.append("### Detected Tech Stack")
            for tech in self.tech_stack_detected:
                lines.append(f"- {tech}")
            lines.append("")

        # Questions that must be answered
        if self.questions:
            lines.append("### Questions You Must Answer Before Migrating")
            lines.append("")
            for i, q in enumerate(self.questions, 1):
                lines.append(f"#### {i}. {q.question}")
                lines.append(f"**Category**: {q.category}")
                lines.append(f"**Why this matters**: {q.why_it_matters}")
                if q.default_assumption:
                    lines.append(f"**Default assumption (VERIFY!)**: {q.default_assumption}")
                if q.options:
                    lines.append("**Possible answers**:")
                    for opt in q.options:
                        lines.append(f"  - {opt}")
                lines.append("")

        # Detected changes
        if self.detected_changes:
            lines.append("### Detected Changes Requiring Migration")
            lines.append("")

            # Group by risk
            high_risk = [c for c in self.detected_changes if c.risk == MigrationRisk.HIGH]
            medium_risk = [c for c in self.detected_changes if c.risk == MigrationRisk.MEDIUM]
            other = [c for c in self.detected_changes if c.risk not in (MigrationRisk.HIGH, MigrationRisk.MEDIUM)]

            for risk_level, changes, emoji in [
                ("HIGH RISK", high_risk, "🔴"),
                ("MEDIUM RISK", medium_risk, "🟡"),
                ("OTHER", other, "🟢"),
            ]:
                if changes:
                    lines.append(f"#### {emoji} {risk_level}")
                    for change in changes:
                        lines.append(f"**{change.description}**")
                        lines.append(f"- Type: {change.change_type.value}")
                        lines.append(f"- File: `{change.file}`")
                        lines.append(f"- Detection confidence: {change.confidence}")

                        if change.assumptions:
                            lines.append("- **VERIFY THESE ASSUMPTIONS**:")
                            for assumption in change.assumptions:
                                lines.append(f"  - [ ] {assumption}")

                        if change.questions:
                            lines.append("- **Answer these questions**:")
                            for q in change.questions:
                                lines.append(f"  - {q}")

                        if change.considerations:
                            lines.append("- **Considerations**:")
                            for c in change.considerations:
                                lines.append(f"  - {c}")

                        if change.documentation_links:
                            lines.append("- **Documentation**:")
                            for link in change.documentation_links:
                                lines.append(f"  - {link}")

                        lines.append("")
        else:
            lines.append("### No Changes Detected")
            lines.append("")
            lines.append("No schema, configuration, or dependency changes were detected.")
            lines.append("This could mean:")
            lines.append("- The changes are purely in application code")
            lines.append("- The analysis couldn't detect the changes")
            lines.append("- There truly are no infrastructure/data changes")
            lines.append("")

        # General considerations
        if self.general_considerations:
            lines.append("### General Migration Considerations")
            for consideration in self.general_considerations:
                lines.append(f"- [ ] {consideration}")
            lines.append("")

        # Assumptions
        if self.assumptions:
            lines.append("### Assumptions Made in This Assessment")
            lines.append("**You must verify each of these:**")
            for assumption in self.assumptions:
                lines.append(f"- [ ] {assumption}")
            lines.append("")

        # Documentation links
        if self.documentation_links:
            lines.append("### Relevant Documentation")
            for link in self.documentation_links:
                lines.append(f"- {link}")
            lines.append("")

        # Next steps
        lines.append("### Next Steps")
        if self.next_steps:
            for i, step in enumerate(self.next_steps, 1):
                lines.append(f"{i}. {step}")
        else:
            lines.append("1. Answer all questions in the questionnaire above")
            lines.append("2. Verify all assumptions marked with [ ]")
            lines.append("3. Review documentation for your specific tech stack")
            lines.append("4. Create your actual migration plan based on your answers")
            lines.append("5. Test the migration in a staging environment")
            lines.append("6. Plan rollback procedures and test them")
            lines.append("7. Execute migration with monitoring in place")
        lines.append("")

        # Final note
        lines.append("---")
        lines.append("*This assessment was generated by static analysis. It cannot verify")
        lines.append("runtime behavior, actual system state, or deployment-specific constraints.")
        lines.append("Always test migrations in non-production environments first.*")

        return "\n".join(lines)


# ============================================================================
# STANDARD MIGRATION QUESTIONS
# ============================================================================

STANDARD_QUESTIONS = [
    MigrationQuestion(
        question="Do you have shared state between old and new versions?",
        category="state",
        why_it_matters="Shared state (sessions, caches, locks) can cause issues during gradual rollout. If both versions write to the same state store, data corruption is possible.",
        default_assumption="Assuming stateless application",
        options=[
            "No shared state - each request is independent",
            "Shared database - both versions read/write same DB",
            "Shared cache (Redis, Memcached)",
            "Shared session store",
            "Other shared state",
        ],
    ),
    MigrationQuestion(
        question="What is your current deployment mechanism?",
        category="deployment",
        why_it_matters="The deployment mechanism determines what migration strategies are available. Kubernetes blue-green differs from EC2 rolling updates.",
        options=[
            "Kubernetes (can do blue-green, canary)",
            "Docker Compose / Swarm",
            "Serverless (Lambda, Cloud Functions)",
            "Traditional VM/EC2 instances",
            "Platform-as-a-Service (Heroku, Railway)",
            "Manual deployment",
        ],
    ),
    MigrationQuestion(
        question="What is your current rollback capability?",
        category="rollback",
        why_it_matters="You need to know how quickly you can revert if the migration fails. Database rollbacks are especially complex.",
        options=[
            "Instant rollback (keep old version running)",
            "Quick redeploy of previous version",
            "Database migration has down migration",
            "No automated rollback - manual process",
        ],
    ),
    MigrationQuestion(
        question="Are there database schema changes?",
        category="data",
        why_it_matters="Schema changes are the riskiest part of migrations. Adding columns is safe; removing or renaming columns requires data migration.",
        default_assumption="No schema changes detected, but verify manually",
        options=[
            "No schema changes",
            "Adding new columns/tables only (expand)",
            "Removing columns/tables (contract)",
            "Renaming columns/tables",
            "Changing column types",
            "Adding constraints (foreign keys, NOT NULL)",
        ],
    ),
    MigrationQuestion(
        question="What is your acceptable downtime window?",
        category="deployment",
        why_it_matters="Different migration strategies have different downtime profiles. True zero-downtime requires careful coordination.",
        options=[
            "Zero downtime required",
            "Brief downtime acceptable (< 1 minute)",
            "Maintenance window available (specify length)",
            "Downtime acceptable if notified in advance",
        ],
    ),
    MigrationQuestion(
        question="How will you verify the migration succeeded?",
        category="verification",
        why_it_matters="You need clear success criteria before you migrate. What metrics, tests, or checks will confirm success?",
        options=[
            "Automated health checks / readiness probes",
            "Automated integration tests post-deploy",
            "Manual verification checklist",
            "Monitoring dashboards and alerts",
            "Customer-facing smoke tests",
        ],
    ),
]


# ============================================================================
# CHANGE DETECTION
# ============================================================================

# Patterns that indicate schema changes
SCHEMA_CHANGE_PATTERNS = {
    # SQL migrations
    r'CREATE\s+TABLE': {"type": ChangeType.SCHEMA, "risk": MigrationRisk.MEDIUM, "desc": "New table creation"},
    r'DROP\s+TABLE': {"type": ChangeType.SCHEMA, "risk": MigrationRisk.HIGH, "desc": "Table deletion"},
    r'ALTER\s+TABLE.*ADD\s+COLUMN': {"type": ChangeType.SCHEMA, "risk": MigrationRisk.LOW, "desc": "Column addition"},
    r'ALTER\s+TABLE.*DROP\s+COLUMN': {"type": ChangeType.SCHEMA, "risk": MigrationRisk.HIGH, "desc": "Column removal"},
    r'ALTER\s+TABLE.*MODIFY|ALTER\s+TABLE.*CHANGE': {"type": ChangeType.SCHEMA, "risk": MigrationRisk.HIGH, "desc": "Column modification"},
    r'ALTER\s+TABLE.*RENAME': {"type": ChangeType.SCHEMA, "risk": MigrationRisk.HIGH, "desc": "Table/column rename"},
    r'ADD\s+CONSTRAINT|ADD\s+FOREIGN\s+KEY': {"type": ChangeType.SCHEMA, "risk": MigrationRisk.MEDIUM, "desc": "Constraint addition"},

    # ORM migrations (Django, Rails, etc.)
    r'migrations\.CreateModel|CreateModel': {"type": ChangeType.SCHEMA, "risk": MigrationRisk.MEDIUM, "desc": "ORM model creation"},
    r'migrations\.DeleteModel|DeleteModel': {"type": ChangeType.SCHEMA, "risk": MigrationRisk.HIGH, "desc": "ORM model deletion"},
    r'migrations\.AddField|AddField': {"type": ChangeType.SCHEMA, "risk": MigrationRisk.LOW, "desc": "ORM field addition"},
    r'migrations\.RemoveField|RemoveField': {"type": ChangeType.SCHEMA, "risk": MigrationRisk.HIGH, "desc": "ORM field removal"},
    r'migrations\.AlterField|AlterField': {"type": ChangeType.SCHEMA, "risk": MigrationRisk.MEDIUM, "desc": "ORM field alteration"},
    r'migrations\.RenameField|RenameField': {"type": ChangeType.SCHEMA, "risk": MigrationRisk.HIGH, "desc": "ORM field rename"},

    # Prisma, TypeORM, Sequelize
    r'prisma\s+migrate|db\s+push': {"type": ChangeType.SCHEMA, "risk": MigrationRisk.MEDIUM, "desc": "Prisma migration"},
    r'synchronize:\s*true': {"type": ChangeType.SCHEMA, "risk": MigrationRisk.HIGH, "desc": "TypeORM auto-sync (dangerous in production)"},
}

# API change patterns
API_CHANGE_PATTERNS = {
    r'@deprecated|@Deprecated': {"type": ChangeType.API, "risk": MigrationRisk.MEDIUM, "desc": "Deprecated endpoint"},
    r'router\.(delete|remove)|app\.delete': {"type": ChangeType.API, "risk": MigrationRisk.HIGH, "desc": "Endpoint removal"},
    r'breaking.*change|BREAKING': {"type": ChangeType.API, "risk": MigrationRisk.HIGH, "desc": "Breaking change noted"},
}

# Config change patterns
CONFIG_CHANGE_PATTERNS = {
    r'environment|ENV|env\.': {"type": ChangeType.CONFIG, "risk": MigrationRisk.MEDIUM, "desc": "Environment configuration"},
    r'DATABASE_URL|DB_HOST|REDIS_URL': {"type": ChangeType.CONFIG, "risk": MigrationRisk.HIGH, "desc": "Database connection change"},
    r'SECRET_KEY|API_KEY|JWT_SECRET': {"type": ChangeType.CONFIG, "risk": MigrationRisk.HIGH, "desc": "Secret/key configuration"},
}

# Infrastructure patterns
INFRA_CHANGE_PATTERNS = {
    r'resource\s+"': {"type": ChangeType.INFRASTRUCTURE, "risk": MigrationRisk.MEDIUM, "desc": "Terraform resource change"},
    r'replicas:|replicas\s*=': {"type": ChangeType.INFRASTRUCTURE, "risk": MigrationRisk.LOW, "desc": "Replica count change"},
    r'image:|image\s*=': {"type": ChangeType.INFRASTRUCTURE, "risk": MigrationRisk.MEDIUM, "desc": "Container image change"},
}

# Dependency patterns
DEPENDENCY_CHANGE_PATTERNS = {
    r'"dependencies":|dependencies\s*=': {"type": ChangeType.DEPENDENCY, "risk": MigrationRisk.LOW, "desc": "Dependency change"},
    r'requirements\.txt|Pipfile|pyproject\.toml': {"type": ChangeType.DEPENDENCY, "risk": MigrationRisk.LOW, "desc": "Python dependency change"},
    r'package\.json|yarn\.lock|package-lock': {"type": ChangeType.DEPENDENCY, "risk": MigrationRisk.LOW, "desc": "Node dependency change"},
}

# Technology-specific documentation
TECH_DOCUMENTATION = {
    "django": [
        "Django Migrations: https://docs.djangoproject.com/en/stable/topics/migrations/",
        "Django Deployment Checklist: https://docs.djangoproject.com/en/stable/howto/deployment/checklist/",
    ],
    "rails": [
        "Rails Migrations: https://guides.rubyonrails.org/active_record_migrations.html",
        "Rails Zero Downtime: https://github.com/LendingHome/zero_downtime_migrations",
    ],
    "prisma": [
        "Prisma Migrate: https://www.prisma.io/docs/concepts/components/prisma-migrate",
        "Prisma Production: https://www.prisma.io/docs/guides/deployment/deploy-database-changes-with-prisma-migrate",
    ],
    "kubernetes": [
        "Kubernetes Rolling Updates: https://kubernetes.io/docs/tutorials/kubernetes-basics/update/update-intro/",
        "Blue-Green Deployments: https://kubernetes.io/blog/2018/04/30/zero-downtime-deployment-kubernetes-jenkins/",
    ],
    "postgresql": [
        "PostgreSQL ALTER TABLE: https://www.postgresql.org/docs/current/ddl-alter.html",
        "PostgreSQL Migration Patterns: https://www.postgresql.org/docs/current/ddl-alter.html#DDL-ALTER-ADDING-A-COLUMN",
    ],
    "mysql": [
        "MySQL ALTER TABLE: https://dev.mysql.com/doc/refman/8.0/en/alter-table.html",
        "MySQL Online DDL: https://dev.mysql.com/doc/refman/8.0/en/innodb-online-ddl-operations.html",
    ],
}


def detect_tech_stack(cwd: str) -> list[str]:
    """Detect the technology stack from project files."""
    detected = []

    file_indicators = {
        "manage.py": "django",
        "settings.py": "django",
        "Gemfile": "rails",
        "config/routes.rb": "rails",
        "prisma/schema.prisma": "prisma",
        "package.json": "node",
        "go.mod": "go",
        "Cargo.toml": "rust",
        "pom.xml": "java",
        "build.gradle": "java",
        "requirements.txt": "python",
        "pyproject.toml": "python",
        "docker-compose.yml": "docker",
        "docker-compose.yaml": "docker",
        "Dockerfile": "docker",
        "kubernetes/": "kubernetes",
        "k8s/": "kubernetes",
        "*.tf": "terraform",
    }

    for indicator, tech in file_indicators.items():
        if "*" in indicator:
            # Glob pattern
            import glob
            if glob.glob(os.path.join(cwd, indicator)):
                if tech not in detected:
                    detected.append(tech)
        elif indicator.endswith("/"):
            # Directory
            if os.path.isdir(os.path.join(cwd, indicator.rstrip("/"))):
                if tech not in detected:
                    detected.append(tech)
        else:
            # File
            if os.path.exists(os.path.join(cwd, indicator)):
                if tech not in detected:
                    detected.append(tech)

    return detected


def scan_for_changes(cwd: str, patterns: dict, file_extensions: set) -> list[DetectedChange]:
    """Scan codebase for patterns indicating changes."""
    changes = []
    files_scanned = 0
    max_files = 200

    for root, dirs, files in os.walk(cwd):
        dirs[:] = [d for d in dirs if d not in {
            "node_modules", "vendor", "__pycache__", ".git",
            ".venv", "venv", "dist", "build", "target", ".next"
        }]

        for filename in files:
            ext = os.path.splitext(filename)[1]
            if ext not in file_extensions and filename not in file_extensions:
                continue

            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, cwd)

            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                for pattern, info in patterns.items():
                    if re.search(pattern, content, re.IGNORECASE):
                        changes.append(DetectedChange(
                            change_type=info["type"],
                            description=info["desc"],
                            file=rel_path,
                            risk=info["risk"],
                            confidence="detected",
                            assumptions=[f"Pattern '{pattern[:30]}...' detected in file"],
                            considerations=[f"Review the actual changes in {rel_path}"],
                        ))

                files_scanned += 1
                if files_scanned >= max_files:
                    break

            except Exception:
                continue

        if files_scanned >= max_files:
            break

    # Deduplicate by description + file
    seen = set()
    deduped = []
    for change in changes:
        key = (change.description, change.file)
        if key not in seen:
            seen.add(key)
            deduped.append(change)

    return deduped


# ============================================================================
# AI ANALYSIS
# ============================================================================

MIGRATION_ANALYSIS_PROMPT = """Analyze the following code changes for migration implications.

DO NOT generate a migration plan. Instead, identify:
1. Changes that require careful migration (schema, API, config)
2. Questions the user must answer before migrating
3. Assumptions being made that need verification
4. Risks and considerations specific to these changes

DETECTED TECH STACK:
{tech_stack}

CHANGED FILES / NEW CODE:
{code_content}

PREVIOUS CODE (if available):
{previous_code}

Respond in JSON format:
{{
  "detected_changes": [
    {{
      "change_type": "schema|api|config|infrastructure|dependency|code",
      "description": "what changed",
      "file": "filepath",
      "risk": "high|medium|low",
      "questions": ["question user must answer"],
      "assumptions": ["assumption that needs verification"],
      "considerations": ["things to consider for this change"]
    }}
  ],
  "additional_questions": [
    {{
      "question": "question text",
      "category": "state|deployment|rollback|data|dependencies|verification",
      "why_it_matters": "explanation",
      "options": ["option1", "option2"]
    }}
  ],
  "warnings": ["critical warnings"],
  "assumptions": ["general assumptions made"]
}}
"""


def run_ai_migration_analysis(
    cwd: str,
    tech_stack: list[str],
    code_content: str,
    previous_code: str,
    provider,
) -> dict:
    """Run AI analysis for migration insights."""
    prompt = MIGRATION_ANALYSIS_PROMPT.format(
        tech_stack=", ".join(tech_stack) or "Unknown",
        code_content=code_content[:15000] if code_content else "No new code provided",
        previous_code=previous_code[:15000] if previous_code else "No previous code available",
    )

    try:
        result = provider.ask(prompt, "", cwd)

        if not result.success or not result.content:
            return {}

        content = result.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        return json.loads(content.strip())

    except Exception:
        return {}


# ============================================================================
# MAIN FUNCTION
# ============================================================================

def execute_migrate(prompt, previous, step, memory, config, cwd, cost_manager=None) -> dict:
    """Execute migration planning assessment.

    IMPORTANT: This does NOT generate a migration plan.
    It generates an assessment questionnaire that helps the user
    create their own migration plan.

    Arguments (via step.args):
        --quick: Skip AI analysis
        --previous PATH: Path to previous version for comparison

    Returns:
        dict with success, assessment (structured), markdown (display)
    """
    previous_output = previous or {}

    Display.phase("migrate", "Analyzing codebase for migration assessment...")
    Display.notify("Note: This generates a migration QUESTIONNAIRE, not a plan.")

    # Parse arguments
    quick_mode = False
    previous_path = None

    if step.args:
        i = 0
        while i < len(step.args):
            arg = str(step.args[i]).lower()
            if arg in ("--quick", "quick"):
                quick_mode = True
            elif arg in ("--previous", "previous") and i + 1 < len(step.args):
                previous_path = str(step.args[i + 1])
                i += 1
            i += 1

    start_time = time.time()
    assessment = MigrationAssessment()

    # Step 1: Detect tech stack
    Display.notify("Detecting technology stack...")
    tech_stack = detect_tech_stack(cwd)
    assessment.tech_stack_detected = tech_stack
    Display.notify(f"Detected: {', '.join(tech_stack) if tech_stack else 'Unknown'}")

    # Step 2: Add relevant documentation links
    for tech in tech_stack:
        if tech in TECH_DOCUMENTATION:
            assessment.documentation_links.extend(TECH_DOCUMENTATION[tech])

    # Step 3: Scan for change patterns
    Display.notify("Scanning for migration-relevant changes...")

    all_patterns = {}
    all_patterns.update(SCHEMA_CHANGE_PATTERNS)
    all_patterns.update(API_CHANGE_PATTERNS)
    all_patterns.update(CONFIG_CHANGE_PATTERNS)
    all_patterns.update(INFRA_CHANGE_PATTERNS)
    all_patterns.update(DEPENDENCY_CHANGE_PATTERNS)

    # Extensions to scan
    scan_extensions = {
        ".py", ".rb", ".js", ".ts", ".sql", ".prisma",
        ".tf", ".yml", ".yaml", ".json", ".toml",
        ".java", ".go", ".rs", ".php",
        "migrations", "migrate",  # Common migration directory names
    }

    detected_changes = scan_for_changes(cwd, all_patterns, scan_extensions)
    assessment.detected_changes = detected_changes

    Display.notify(f"Detected {len(detected_changes)} potential migration items")

    # Step 4: Add standard questions
    assessment.questions = STANDARD_QUESTIONS.copy()

    # Add tech-specific questions
    if "django" in tech_stack:
        assessment.questions.append(MigrationQuestion(
            question="Have you tested the Django migrations on a copy of production data?",
            category="data",
            why_it_matters="Django migrations can behave differently with real data volumes and edge cases.",
        ))

    if "kubernetes" in tech_stack:
        assessment.questions.append(MigrationQuestion(
            question="Does your Kubernetes setup support blue-green or canary deployments?",
            category="deployment",
            why_it_matters="Kubernetes rollout strategy affects how you can achieve minimal downtime.",
            options=[
                "Yes - using Deployment with RollingUpdate",
                "Yes - using Argo Rollouts or similar",
                "No - manual deployment process",
            ],
        ))

    # Step 5: AI analysis (if not quick mode)
    tokens_used = 0
    if not quick_mode:
        try:
            default_provider_name = config.get("providers", {}).get("default", "claude")
            provider = get_provider(default_provider_name, config)

            # Get code content from previous pipeline step if available
            code_content = previous_output.get("content", "")
            previous_code = ""

            if previous_path and os.path.exists(previous_path):
                try:
                    with open(previous_path, "r") as f:
                        previous_code = f.read()
                except Exception:
                    pass

            Display.notify("Running AI analysis for deeper insights...")
            ai_result = run_ai_migration_analysis(
                cwd, tech_stack, code_content, previous_code, provider
            )

            # Add AI-detected changes
            for change_data in ai_result.get("detected_changes", []):
                try:
                    change_type = ChangeType(change_data.get("change_type", "code"))
                    risk = MigrationRisk(change_data.get("risk", "unknown"))
                except ValueError:
                    change_type = ChangeType.CODE
                    risk = MigrationRisk.UNKNOWN

                assessment.detected_changes.append(DetectedChange(
                    change_type=change_type,
                    description=change_data.get("description", "AI-detected change"),
                    file=change_data.get("file", "[AI analysis]"),
                    risk=risk,
                    confidence="inferred",
                    questions=change_data.get("questions", []),
                    assumptions=change_data.get("assumptions", []),
                    considerations=change_data.get("considerations", []),
                ))

            # Add AI-suggested questions
            for q_data in ai_result.get("additional_questions", []):
                assessment.questions.append(MigrationQuestion(
                    question=q_data.get("question", ""),
                    category=q_data.get("category", "general"),
                    why_it_matters=q_data.get("why_it_matters", ""),
                    options=q_data.get("options", []),
                ))

            # Add AI warnings and assumptions
            assessment.warnings.extend(ai_result.get("warnings", []))
            assessment.assumptions.extend(ai_result.get("assumptions", []))

        except Exception as e:
            Display.notify(f"AI analysis skipped: {str(e)[:50]}")

    # Step 6: Add general considerations
    assessment.general_considerations = [
        "Test migration on a copy of production data before executing",
        "Have a rollback plan and test it",
        "Monitor application health closely during and after migration",
        "Communicate maintenance window to stakeholders if any downtime",
        "Keep old version running until new version is verified",
        "Document any manual steps required",
    ]

    # Add risk-specific considerations
    high_risk_changes = [c for c in assessment.detected_changes if c.risk == MigrationRisk.HIGH]
    if high_risk_changes:
        assessment.warnings.append(
            f"Found {len(high_risk_changes)} HIGH RISK changes - extra caution required"
        )
        assessment.general_considerations.insert(0, "Consider a phased migration approach")

    # Step 7: Standard assumptions
    assessment.assumptions.extend([
        "You have a staging environment that mirrors production",
        "You can deploy both old and new versions simultaneously (for blue-green)",
        "Database changes are backward-compatible during transition",
        "You have monitoring in place to detect issues quickly",
    ])

    # Step 8: Calculate confidence summary
    detected_count = len(assessment.detected_changes)
    inferred_count = len([c for c in assessment.detected_changes if c.confidence == "inferred"])

    if detected_count == 0:
        assessment.confidence_summary = "LOW - No migration-relevant changes detected. This could mean changes are purely in code, or the analysis missed them. Manual review recommended."
    elif inferred_count > detected_count / 2:
        assessment.confidence_summary = "MEDIUM - Many changes were inferred by AI analysis. Verify all assumptions."
    else:
        assessment.confidence_summary = "HIGH - Changes were detected from code patterns. Still verify assumptions."

    # Step 9: Next steps
    assessment.next_steps = [
        "Answer all questions in the questionnaire",
        "Verify all assumptions marked with [ ]",
        "For HIGH RISK changes, plan extra carefully",
        "Test migration on staging with production data copy",
        "Prepare rollback procedures and test them",
        "Create your actual migration runbook based on this assessment",
        "Execute with monitoring and be ready to rollback",
    ]

    duration = time.time() - start_time

    # Log to memory
    memory.write(MemoryEntry(
        timestamp=time.time(),
        phase="migrate",
        agent="migration_assessor",
        type="migration_assessment",
        content=f"Detected {len(assessment.detected_changes)} migration items",
        metadata={
            "changes_count": len(assessment.detected_changes),
            "questions_count": len(assessment.questions),
            "tech_stack": tech_stack,
            "quick_mode": quick_mode,
            "duration": duration,
        },
    ))

    # Display summary
    if assessment.detected_changes:
        high_risk = len([c for c in assessment.detected_changes if c.risk == MigrationRisk.HIGH])
        Display.notify(f"Found {len(assessment.detected_changes)} items ({high_risk} high risk)")
    else:
        Display.notify("No migration-specific changes detected - review manually")

    # Final reminder
    Display.notify(
        "REMINDER: This is an assessment, not a plan. "
        "Answer the questions and verify assumptions before creating your migration plan."
    )

    return {
        "success": True,
        "assessment": assessment.to_dict(),
        "markdown": assessment.to_markdown(),
        "content": assessment.to_markdown(),
        "changes_count": len(assessment.detected_changes),
        "questions_count": len(assessment.questions),
        "tech_stack": tech_stack,
        "quick_mode": quick_mode,
        "duration": duration,
        "tokens_used": tokens_used,
        "files_changed": previous_output.get("files_changed", []),
    }

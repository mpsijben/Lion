"""cost() - Infrastructure Cost Assessment

IMPORTANT: This function does NOT generate cost estimates.

LLM-generated cost numbers are unreliable and potentially dangerous:
- Cloud pricing is complex, region-dependent, and changes frequently
- LLM training data is months stale relative to current pricing
- Usage patterns, data volumes, and storage growth cannot be detected from code
- Users may make budget decisions based on hallucinated estimates

Instead, this function generates:
1. A COST CHECKLIST of all cost-relevant components detected
2. PRICING FACTORS you should look up for each component
3. DIRECT LINKS to cloud pricing calculators
4. QUESTIONS about usage patterns that affect cost

The user plugs in real numbers using the pricing tools and their actual usage data.
"""

import fnmatch
import json
import os
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

from ..memory import MemoryEntry
from ..display import Display
from ..providers import get_provider
from .utils import (
    detect_project_language,
    extract_json_from_llm_response,
    MAX_INFRA_FILES,
    MAX_FILE_CHARS,
)


# ============================================================================
# INFRASTRUCTURE DETECTION PATTERNS
# ============================================================================

INFRASTRUCTURE_FILES = {
    # Container/Docker
    "Dockerfile": {"type": "container", "provider": "docker"},
    "docker-compose.yml": {"type": "container", "provider": "docker-compose"},
    "docker-compose.yaml": {"type": "container", "provider": "docker-compose"},

    # Kubernetes
    "kubernetes.yml": {"type": "orchestration", "provider": "kubernetes"},
    "kubernetes.yaml": {"type": "orchestration", "provider": "kubernetes"},
    "k8s.yml": {"type": "orchestration", "provider": "kubernetes"},
    "k8s.yaml": {"type": "orchestration", "provider": "kubernetes"},
    "deployment.yml": {"type": "orchestration", "provider": "kubernetes"},
    "deployment.yaml": {"type": "orchestration", "provider": "kubernetes"},

    # Terraform
    "*.tf": {"type": "iac", "provider": "terraform"},
    "terraform.tfvars": {"type": "iac", "provider": "terraform"},

    # Cloud-specific
    "serverless.yml": {"type": "serverless", "provider": "serverless-framework"},
    "serverless.yaml": {"type": "serverless", "provider": "serverless-framework"},
    "sam.yml": {"type": "serverless", "provider": "aws-sam"},
    "sam.yaml": {"type": "serverless", "provider": "aws-sam"},
    "template.yaml": {"type": "serverless", "provider": "aws-sam"},
    "cdk.json": {"type": "iac", "provider": "aws-cdk"},
    "pulumi.yaml": {"type": "iac", "provider": "pulumi"},
    "pulumi.yml": {"type": "iac", "provider": "pulumi"},

    # Vercel/Netlify
    "vercel.json": {"type": "serverless", "provider": "vercel"},
    "netlify.toml": {"type": "serverless", "provider": "netlify"},

    # Heroku
    "Procfile": {"type": "paas", "provider": "heroku"},
    "app.json": {"type": "paas", "provider": "heroku"},

    # Railway/Render
    "railway.toml": {"type": "paas", "provider": "railway"},
    "render.yaml": {"type": "paas", "provider": "render"},

    # CI/CD (impacts costs too)
    ".github/workflows/*.yml": {"type": "ci", "provider": "github-actions"},
    ".gitlab-ci.yml": {"type": "ci", "provider": "gitlab-ci"},
    "azure-pipelines.yml": {"type": "ci", "provider": "azure-devops"},
}

# Patterns in code that indicate cloud services
SERVICE_PATTERNS = {
    # AWS
    r'boto3|aws-sdk|@aws-sdk|AmazonWebServices': {"service": "aws", "confidence": "high"},
    r's3://|S3Client|S3Bucket': {"service": "aws-s3", "confidence": "high"},
    r'dynamodb|DynamoDB': {"service": "aws-dynamodb", "confidence": "high"},
    r'lambda_handler|AWS::Lambda': {"service": "aws-lambda", "confidence": "high"},
    r'SQS|sqs\.': {"service": "aws-sqs", "confidence": "medium"},
    r'SNS|sns\.': {"service": "aws-sns", "confidence": "medium"},
    r'cognito|Cognito': {"service": "aws-cognito", "confidence": "medium"},
    r'cloudfront|CloudFront': {"service": "aws-cloudfront", "confidence": "medium"},
    r'RDS|rds\.': {"service": "aws-rds", "confidence": "medium"},

    # GCP
    r'google-cloud|@google-cloud|googleapis': {"service": "gcp", "confidence": "high"},
    r'BigQuery|bigquery': {"service": "gcp-bigquery", "confidence": "high"},
    r'firestore|Firestore': {"service": "gcp-firestore", "confidence": "high"},
    r'cloud-storage|storage\.googleapis': {"service": "gcp-storage", "confidence": "high"},
    r'cloud-functions|functions-framework': {"service": "gcp-functions", "confidence": "high"},
    r'pubsub|PubSub': {"service": "gcp-pubsub", "confidence": "medium"},

    # Azure
    r'azure|@azure|WindowsAzure': {"service": "azure", "confidence": "high"},
    r'cosmos|CosmosDB': {"service": "azure-cosmos", "confidence": "high"},
    r'blob\.core\.windows': {"service": "azure-blob", "confidence": "high"},
    r'azure-functions': {"service": "azure-functions", "confidence": "high"},

    # Databases
    r'mongodb|MongoClient|mongoose': {"service": "mongodb", "confidence": "high"},
    r'postgres|pg\.|psycopg|PostgreSQL': {"service": "postgresql", "confidence": "high"},
    r'mysql|MySQL': {"service": "mysql", "confidence": "high"},
    r'redis|Redis|ioredis': {"service": "redis", "confidence": "high"},
    r'elasticsearch|ElasticSearch': {"service": "elasticsearch", "confidence": "high"},

    # Third-party APIs with costs
    r'stripe|Stripe': {"service": "stripe", "confidence": "high"},
    r'twilio|Twilio': {"service": "twilio", "confidence": "high"},
    r'sendgrid|SendGrid': {"service": "sendgrid", "confidence": "high"},
    r'openai|OpenAI|gpt-': {"service": "openai", "confidence": "high"},
    r'anthropic|Anthropic|claude': {"service": "anthropic", "confidence": "high"},
    r'algolia|Algolia': {"service": "algolia", "confidence": "high"},
    r'cloudflare|Cloudflare': {"service": "cloudflare", "confidence": "high"},
    r'auth0|Auth0': {"service": "auth0", "confidence": "medium"},
    r'firebase|Firebase': {"service": "firebase", "confidence": "high"},

    # Message queues
    r'rabbitmq|RabbitMQ|amqp': {"service": "rabbitmq", "confidence": "high"},
    r'kafka|Kafka': {"service": "kafka", "confidence": "high"},
}

# Pricing calculator links
PRICING_CALCULATORS = {
    "aws": "https://calculator.aws/",
    "aws-s3": "https://calculator.aws/#/createCalculator/S3",
    "aws-lambda": "https://calculator.aws/#/createCalculator/Lambda",
    "aws-dynamodb": "https://calculator.aws/#/createCalculator/DynamoDB",
    "aws-rds": "https://calculator.aws/#/createCalculator/RDS",
    "aws-sqs": "https://calculator.aws/#/createCalculator/SQS",
    "aws-cloudfront": "https://calculator.aws/#/createCalculator/CloudFront",
    "gcp": "https://cloud.google.com/products/calculator",
    "gcp-bigquery": "https://cloud.google.com/products/calculator#id=cdaa7c41-e6cd-4f5e-9f6f-0e5e5d3d5f5d",
    "gcp-storage": "https://cloud.google.com/products/calculator#id=storage",
    "azure": "https://azure.microsoft.com/en-us/pricing/calculator/",
    "azure-cosmos": "https://azure.microsoft.com/en-us/pricing/calculator/?service=cosmos-db",
    "vercel": "https://vercel.com/pricing",
    "netlify": "https://www.netlify.com/pricing/",
    "stripe": "https://stripe.com/pricing",
    "twilio": "https://www.twilio.com/pricing",
    "sendgrid": "https://sendgrid.com/pricing/",
    "openai": "https://openai.com/pricing",
    "anthropic": "https://www.anthropic.com/pricing",
    "mongodb": "https://www.mongodb.com/pricing",
    "redis": "https://redis.com/redis-enterprise-cloud/pricing/",
    "elasticsearch": "https://www.elastic.co/pricing/",
    "auth0": "https://auth0.com/pricing/",
    "firebase": "https://firebase.google.com/pricing",
    "algolia": "https://www.algolia.com/pricing/",
    "cloudflare": "https://www.cloudflare.com/plans/",
    "heroku": "https://www.heroku.com/pricing",
    "railway": "https://railway.app/pricing",
    "render": "https://render.com/pricing",
}


@dataclass
class DetectedComponent:
    """A detected infrastructure component with cost implications."""
    name: str
    type: str  # compute, storage, database, api, messaging, etc.
    source_file: str
    confidence: str  # high, medium, low
    pricing_factors: list[str] = field(default_factory=list)
    pricing_calculator: Optional[str] = None
    questions: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CostAssessment:
    """Structured cost assessment output."""
    components: list[DetectedComponent] = field(default_factory=list)
    infrastructure_files: list[str] = field(default_factory=list)
    missing_info: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "components": [c.to_dict() for c in self.components],
            "infrastructure_files": self.infrastructure_files,
            "missing_info": self.missing_info,
            "questions": self.questions,
            "assumptions": self.assumptions,
            "next_steps": self.next_steps,
            "warnings": self.warnings,
        }

    def to_markdown(self) -> str:
        """Render assessment as markdown for display."""
        lines = []

        # Warning header
        lines.append("## Cost Assessment Checklist")
        lines.append("")
        lines.append("> **Important**: This is NOT a cost estimate. LLM-generated cost numbers")
        lines.append("> are unreliable. Use the links below to calculate actual costs with your")
        lines.append("> real usage data.")
        lines.append("")

        # Warnings
        if self.warnings:
            lines.append("### Warnings")
            for warning in self.warnings:
                lines.append(f"- {warning}")
            lines.append("")

        # Detected components
        if self.components:
            lines.append("### Detected Cost Components")
            lines.append("")
            for comp in self.components:
                lines.append(f"#### {comp.name}")
                lines.append(f"- **Type**: {comp.type}")
                lines.append(f"- **Source**: `{comp.source_file}`")
                lines.append(f"- **Detection confidence**: {comp.confidence}")

                if comp.pricing_calculator:
                    lines.append(f"- **Pricing calculator**: {comp.pricing_calculator}")

                if comp.pricing_factors:
                    lines.append("- **Pricing factors to check**:")
                    for factor in comp.pricing_factors:
                        lines.append(f"  - [ ] {factor}")

                if comp.questions:
                    lines.append("- **Questions you need to answer**:")
                    for q in comp.questions:
                        lines.append(f"  - {q}")

                if comp.assumptions:
                    lines.append("- **Assumptions made** (verify these):")
                    for a in comp.assumptions:
                        lines.append(f"  - {a}")

                lines.append("")
        else:
            lines.append("### No Infrastructure Detected")
            lines.append("")
            lines.append("No infrastructure configuration files were found.")
            lines.append("This function requires at least one of:")
            lines.append("- `Dockerfile` or `docker-compose.yml`")
            lines.append("- `*.tf` (Terraform files)")
            lines.append("- `serverless.yml` or cloud function configs")
            lines.append("- `vercel.json`, `netlify.toml`, etc.")
            lines.append("")

        # Infrastructure files found
        if self.infrastructure_files:
            lines.append("### Infrastructure Files Found")
            for f in self.infrastructure_files:
                lines.append(f"- `{f}`")
            lines.append("")

        # Questions that affect cost
        if self.questions:
            lines.append("### Questions That Affect Cost")
            lines.append("Answer these before estimating costs:")
            lines.append("")
            for i, q in enumerate(self.questions, 1):
                lines.append(f"{i}. {q}")
            lines.append("")

        # Missing information
        if self.missing_info:
            lines.append("### Missing Information")
            lines.append("Could not determine from code:")
            for info in self.missing_info:
                lines.append(f"- {info}")
            lines.append("")

        # Assumptions
        if self.assumptions:
            lines.append("### Assumptions Made")
            lines.append("This assessment assumes:")
            for assumption in self.assumptions:
                lines.append(f"- {assumption}")
            lines.append("")

        # Next steps
        lines.append("### Next Steps")
        if self.next_steps:
            for step in self.next_steps:
                lines.append(f"1. {step}")
        else:
            lines.append("1. Review detected components above")
            lines.append("2. Answer the questions about your usage patterns")
            lines.append("3. Use the pricing calculators linked for each service")
            lines.append("4. Add up the totals for your cost estimate")
        lines.append("")

        return "\n".join(lines)


# ============================================================================
# INFRASTRUCTURE DETECTION
# ============================================================================

def detect_infrastructure_files(cwd: str) -> list[tuple[str, dict]]:
    """Detect infrastructure configuration files.

    Returns list of (filepath, info_dict) tuples.
    """
    found = []

    for root, dirs, files in os.walk(cwd):
        # Skip common non-relevant directories
        dirs[:] = [d for d in dirs if d not in {
            "node_modules", "vendor", "__pycache__", ".git",
            ".venv", "venv", "dist", "build", "target"
        }]

        rel_root = os.path.relpath(root, cwd)
        if rel_root == ".":
            rel_root = ""

        for filename in files:
            rel_path = os.path.join(rel_root, filename) if rel_root else filename

            # Check exact matches
            if filename in INFRASTRUCTURE_FILES:
                found.append((rel_path, INFRASTRUCTURE_FILES[filename]))
                continue

            # Check patterns (e.g., *.tf)
            for pattern, info in INFRASTRUCTURE_FILES.items():
                if "*" in pattern:
                    if fnmatch.fnmatch(filename, pattern.split("/")[-1]):
                        found.append((rel_path, info))
                        break

    return found


def detect_services_in_code(cwd: str, max_files: int = 100) -> list[tuple[str, dict, str]]:
    """Scan code for cloud service usage patterns.

    Returns list of (service_name, info_dict, source_file) tuples.
    """
    found = []
    files_scanned = 0

    # Extensions to scan
    code_extensions = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".java", ".rb", ".rs"}

    for root, dirs, files in os.walk(cwd):
        dirs[:] = [d for d in dirs if d not in {
            "node_modules", "vendor", "__pycache__", ".git",
            ".venv", "venv", "dist", "build", "target"
        }]

        for filename in files:
            ext = os.path.splitext(filename)[1]
            if ext not in code_extensions:
                continue

            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, cwd)

            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                for pattern, info in SERVICE_PATTERNS.items():
                    if re.search(pattern, content, re.IGNORECASE):
                        found.append((info["service"], info, rel_path))

                files_scanned += 1
                if files_scanned >= max_files:
                    break
            except Exception:
                continue

        if files_scanned >= max_files:
            break

    # Deduplicate (keep first occurrence)
    seen = set()
    deduped = []
    for service, info, source in found:
        if service not in seen:
            seen.add(service)
            deduped.append((service, info, source))

    return deduped


def build_component(service: str, info: dict, source_file: str) -> DetectedComponent:
    """Build a DetectedComponent from service detection."""

    # Default pricing factors based on service type
    pricing_factors = []
    questions = []
    assumptions = []

    if "s3" in service or "storage" in service or "blob" in service:
        pricing_factors = [
            "Storage volume (GB)",
            "Number of PUT/COPY/POST requests per month",
            "Number of GET requests per month",
            "Data transfer OUT (GB per month)",
            "Storage class (Standard, IA, Glacier, etc.)",
        ]
        questions = [
            "What's your expected storage growth rate?",
            "How often is data accessed vs. archived?",
            "Do you need cross-region replication?",
        ]
        comp_type = "storage"

    elif "lambda" in service or "functions" in service or "serverless" in service:
        pricing_factors = [
            "Number of requests per month",
            "Average execution duration (ms)",
            "Memory allocated (MB)",
            "Provisioned concurrency (if any)",
        ]
        questions = [
            "What's your expected requests per month?",
            "What's the average function execution time?",
            "Do you need provisioned concurrency for cold start?",
        ]
        comp_type = "compute"

    elif "dynamodb" in service or "cosmos" in service or "firestore" in service:
        pricing_factors = [
            "Read capacity units / RRUs per month",
            "Write capacity units / WRUs per month",
            "Storage (GB)",
            "On-demand vs provisioned capacity",
            "Global tables / multi-region replication",
        ]
        questions = [
            "What's your read/write ratio?",
            "Do you need provisioned capacity or on-demand?",
            "Do you need multi-region?",
        ]
        comp_type = "database"

    elif "rds" in service or "postgres" in service or "mysql" in service:
        pricing_factors = [
            "Instance type (db.t3.micro, db.r5.large, etc.)",
            "Storage (GB)",
            "Multi-AZ deployment",
            "Read replicas",
            "Backup retention",
            "Data transfer",
        ]
        questions = [
            "What instance size do you need?",
            "Do you need Multi-AZ for high availability?",
            "How many read replicas?",
        ]
        comp_type = "database"

    elif "redis" in service:
        pricing_factors = [
            "Node type",
            "Number of nodes",
            "Cluster mode enabled/disabled",
            "Data transfer",
        ]
        questions = [
            "What's your cache size requirement?",
            "Do you need cluster mode?",
            "Is this for caching or as a primary datastore?",
        ]
        comp_type = "cache"

    elif "stripe" in service:
        pricing_factors = [
            "Transaction volume per month",
            "Average transaction value",
            "Geographic distribution (affects interchange)",
            "Stripe Radar usage",
            "Connect fees (if using Connect)",
        ]
        questions = [
            "What's your expected monthly transaction volume?",
            "What's your average transaction size?",
            "Are you using Stripe Connect?",
        ]
        comp_type = "payment"

    elif "twilio" in service:
        pricing_factors = [
            "SMS volume per month",
            "Voice minutes per month",
            "Phone numbers needed",
            "Geographic destinations",
        ]
        questions = [
            "What message/call volume do you expect?",
            "Which countries are you sending to?",
        ]
        comp_type = "communication"

    elif "openai" in service or "anthropic" in service:
        pricing_factors = [
            "Input tokens per month",
            "Output tokens per month",
            "Model used (GPT-4 vs GPT-3.5, Claude vs Haiku, etc.)",
            "Fine-tuning costs (if applicable)",
        ]
        questions = [
            "What model(s) are you using?",
            "What's your expected token volume?",
            "Are you caching responses?",
        ]
        comp_type = "ai-api"

    elif "sqs" in service or "sns" in service or "pubsub" in service or "kafka" in service:
        pricing_factors = [
            "Number of messages per month",
            "Message size (KB)",
            "FIFO vs Standard queues",
            "Data transfer",
        ]
        questions = [
            "What's your message volume?",
            "Do you need ordering guarantees?",
        ]
        comp_type = "messaging"

    elif "cloudfront" in service or "cdn" in service:
        pricing_factors = [
            "Data transfer OUT (GB per month)",
            "Number of HTTP/HTTPS requests",
            "Geographic distribution",
            "Origin requests",
        ]
        questions = [
            "What's your expected bandwidth?",
            "Where are your users located?",
        ]
        comp_type = "cdn"

    else:
        pricing_factors = ["Consult service pricing page"]
        questions = ["Review service-specific pricing model"]
        comp_type = "service"

    # Add general assumption
    assumptions = [
        "Pricing based on public pricing (no negotiated discounts)",
        "No reserved instances or committed use discounts applied",
    ]

    return DetectedComponent(
        name=service,
        type=comp_type,
        source_file=source_file,
        confidence=info.get("confidence", "medium"),
        pricing_factors=pricing_factors,
        pricing_calculator=PRICING_CALCULATORS.get(service),
        questions=questions,
        assumptions=assumptions,
    )


# ============================================================================
# AI ANALYSIS (for deeper insights, not estimates)
# ============================================================================

COST_ANALYSIS_PROMPT = """Analyze the following infrastructure configuration for cost-relevant factors.

DO NOT provide cost estimates or numbers. Instead, identify:
1. Components that have cost implications
2. Scaling factors that affect cost (data volume, request rate, etc.)
3. Missing information needed to estimate costs
4. Potential cost optimization opportunities
5. Hidden costs that might be overlooked

INFRASTRUCTURE FILES:
{infra_content}

CODE PATTERNS DETECTED:
{detected_services}

Respond in JSON format:
{{
  "additional_components": [
    {{
      "name": "component name",
      "type": "compute|storage|database|api|etc",
      "pricing_factors": ["factor1", "factor2"],
      "questions": ["question about usage"],
      "assumptions": ["assumption made"]
    }}
  ],
  "missing_info": ["info needed but not found in code"],
  "cost_risks": ["potential cost risks or surprises"],
  "optimization_opportunities": ["ways to reduce costs"],
  "questions_for_user": ["questions the user should answer"]
}}
"""


def run_ai_cost_analysis(
    cwd: str,
    infra_files: list[tuple[str, dict]],
    detected_services: list[tuple[str, dict, str]],
    provider,
) -> tuple[dict, int]:
    """Run AI analysis for deeper cost insights.

    Returns:
        Tuple of (result_dict, tokens_used) where result_dict contains
        additional_components, missing_info, etc.
    """
    # Read infrastructure file contents
    infra_content = []
    for filepath, info in infra_files[:MAX_INFRA_FILES]:
        full_path = os.path.join(cwd, filepath)
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                if len(content) > MAX_FILE_CHARS:
                    content = content[:MAX_FILE_CHARS] + "\n... [truncated]"
                infra_content.append(f"=== {filepath} ===\n{content}")
        except Exception:
            continue

    # Format detected services
    services_text = "\n".join([
        f"- {service} (in {source})"
        for service, _, source in detected_services
    ])

    prompt = COST_ANALYSIS_PROMPT.format(
        infra_content="\n\n".join(infra_content) or "No infrastructure files found",
        detected_services=services_text or "No cloud services detected in code",
    )

    try:
        result = provider.ask(prompt, "", cwd)

        if not result.success or not result.content:
            return {}, 0

        # Get tokens used from the result
        tokens_used = getattr(result, 'tokens_used', 0) or 0

        # Parse JSON response using shared utility
        parsed = extract_json_from_llm_response(result.content)
        return parsed, tokens_used

    except Exception:
        return {}, 0


# ============================================================================
# MAIN FUNCTION
# ============================================================================

def execute_cost(prompt, previous, step, memory, config, cwd, cost_manager=None) -> dict:
    """Execute infrastructure cost assessment.

    IMPORTANT: This does NOT generate cost estimates.
    It generates a checklist of cost-relevant components with links to
    actual pricing calculators.

    Arguments (via step.args):
        --quick: Skip AI analysis, only detect patterns
        --include-code: Include code analysis for service detection

    Returns:
        dict with success, assessment (structured), markdown (display)
    """
    previous = previous or {}

    Display.phase("cost", "Analyzing infrastructure for cost assessment...")
    Display.notify("Note: This generates a cost CHECKLIST, not estimates.")

    # Parse arguments
    quick_mode = False
    include_code = True

    if step.args:
        for arg in step.args:
            arg_lower = str(arg).lower()
            if arg_lower in ("--quick", "quick"):
                quick_mode = True
            elif arg_lower in ("--no-code", "no-code"):
                include_code = False

    start_time = time.time()
    assessment = CostAssessment()

    # Step 1: Detect infrastructure files
    Display.notify("Detecting infrastructure configuration files...")
    infra_files = detect_infrastructure_files(cwd)

    assessment.infrastructure_files = [f for f, _ in infra_files]

    if not infra_files:
        assessment.warnings.append(
            "No infrastructure configuration files found. "
            "This function works best with Dockerfile, terraform files, "
            "serverless.yml, or similar configuration files."
        )
    else:
        Display.notify(f"Found {len(infra_files)} infrastructure files")

    # Step 2: Detect services in code
    detected_services = []
    if include_code:
        Display.notify("Scanning code for cloud service usage...")
        detected_services = detect_services_in_code(cwd)
        Display.notify(f"Detected {len(detected_services)} cloud services in code")

    # Build components from detections
    for service, info, source in detected_services:
        component = build_component(service, info, source)
        assessment.components.append(component)

    # Add infrastructure file info to components
    for filepath, info in infra_files:
        # Create component for infrastructure type
        comp_type = info.get("type", "infrastructure")
        provider = info.get("provider", "unknown")

        # Only add if not already covered by service detection
        existing_names = {c.name for c in assessment.components}
        if provider not in existing_names:
            calculator = PRICING_CALCULATORS.get(provider)
            assessment.components.append(DetectedComponent(
                name=provider,
                type=comp_type,
                source_file=filepath,
                confidence="high",
                pricing_factors=["See infrastructure file for resource definitions"],
                pricing_calculator=calculator,
                questions=["Review resource specifications in the file"],
                assumptions=[],
            ))

    # Step 3: AI analysis for deeper insights (if not quick mode)
    tokens_used = 0
    if not quick_mode and (infra_files or detected_services):
        try:
            default_provider_name = config.get("providers", {}).get("default", "claude")
            provider = get_provider(default_provider_name, config)

            Display.notify("Running AI analysis for deeper insights...")
            ai_result = run_ai_cost_analysis(
                cwd, infra_files, detected_services, provider
            )

            # Add AI-discovered components
            for comp_data in ai_result.get("additional_components", []):
                assessment.components.append(DetectedComponent(
                    name=comp_data.get("name", "Unknown"),
                    type=comp_data.get("type", "service"),
                    source_file="[AI detected]",
                    confidence="ai-suggested",
                    pricing_factors=comp_data.get("pricing_factors", []),
                    pricing_calculator=None,
                    questions=comp_data.get("questions", []),
                    assumptions=comp_data.get("assumptions", []),
                ))

            # Add other AI insights
            assessment.missing_info.extend(ai_result.get("missing_info", []))
            assessment.questions.extend(ai_result.get("questions_for_user", []))

            # Add optimization opportunities and risks as warnings
            for risk in ai_result.get("cost_risks", []):
                assessment.warnings.append(f"Cost risk: {risk}")
            for opt in ai_result.get("optimization_opportunities", []):
                assessment.next_steps.append(f"Consider: {opt}")

        except Exception as e:
            Display.notify(f"AI analysis skipped: {str(e)[:50]}")

    # Add standard questions if none detected
    if not assessment.questions:
        assessment.questions = [
            "What is your expected traffic (requests/day)?",
            "What is your expected storage growth rate?",
            "What regions do you need to deploy to?",
            "Do you have any committed use or reserved capacity discounts?",
        ]

    # Add standard next steps
    assessment.next_steps.extend([
        "Use the pricing calculators linked for each component",
        "Input your actual usage estimates from the questions above",
        "Add up the component costs for total estimate",
        "Re-assess monthly as usage patterns become clearer",
    ])

    # Standard assumptions
    assessment.assumptions = [
        "Public cloud pricing (no enterprise discounts)",
        "On-demand pricing (no reserved instances)",
        "Single region unless otherwise specified",
        "LLM training data may be stale - verify current pricing",
    ]

    duration = time.time() - start_time

    # Log to memory
    memory.write(MemoryEntry(
        timestamp=time.time(),
        phase="cost",
        agent="cost_assessor",
        type="cost_assessment",
        content=f"Detected {len(assessment.components)} cost components",
        metadata={
            "components_count": len(assessment.components),
            "infra_files_count": len(infra_files),
            "quick_mode": quick_mode,
            "duration": duration,
        },
    ))

    # Display results
    if assessment.components:
        Display.notify(f"Found {len(assessment.components)} cost-relevant components")
    else:
        Display.step_error("cost", "No infrastructure detected - see output for details")

    # Final disclaimer
    Display.notify(
        "REMINDER: Use the pricing calculators above with YOUR usage data. "
        "Do not rely on LLM-generated cost numbers."
    )

    return {
        "success": True,
        "assessment": assessment.to_dict(),
        "markdown": assessment.to_markdown(),
        "content": assessment.to_markdown(),
        "components_count": len(assessment.components),
        "infrastructure_files": assessment.infrastructure_files,
        "quick_mode": quick_mode,
        "duration": duration,
        "tokens_used": tokens_used,
        "files_changed": previous.get("files_changed", []),
    }

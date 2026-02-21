"""create_tests() - Test generation with optional multi-agent deliberation.

Analyzes code and generates comprehensive tests.
Supports pride-style multi-agent mode:
  create_tests()              -- 1 agent (default provider)
  create_tests(3)             -- 3 agents discuss test strategy, then implement
  create_tests(gemini, claude) -- specific agents discuss, then implement
"""

import os
import time
import concurrent.futures
from typing import Optional

from ..memory import MemoryEntry
from ..providers import get_provider, is_provider_name
from ..display import Display
from .utils import (
    detect_project_language,
    detect_test_framework,
    get_source_files,
    get_test_files,
    read_file_content,
    TEST_FRAMEWORK_PATTERNS,
)


CREATE_TESTS_PROMPT = """You are a test engineer. Analyze the following code and create comprehensive tests.

PROJECT LANGUAGE: {language}
TEST FRAMEWORK: {framework}

SOURCE FILES TO TEST:
{source_files}

EXISTING TESTS (for reference/style):
{existing_tests}

ORIGINAL TASK CONTEXT:
{context}

REQUIREMENTS:
1. Create tests for all public functions/methods/classes
2. Include edge cases and error handling tests
3. Follow the project's existing test style if tests exist
4. Use the detected test framework ({framework})
5. Name test files according to the framework convention

For each test file, output:
```{language}
# FILE: <test_file_path>
<test code>
```

Focus on:
- Unit tests for individual functions
- Integration tests for connected components
- Edge cases (empty inputs, null values, boundary conditions)
- Error handling (exceptions, invalid inputs)
- Happy path scenarios

Generate comprehensive, runnable tests.
"""

PROPOSE_TESTS_PROMPT = """You are Agent {agent_num} in a team of {total_agents} test engineers.

Analyze the code below and propose a TEST STRATEGY. Do NOT write the actual test code yet.

PROJECT LANGUAGE: {language}
TEST FRAMEWORK: {framework}

SOURCE FILES:
{source_files}

EXISTING TESTS (for reference):
{existing_tests}

ORIGINAL TASK: {context}

Propose:
1. Which files/functions need tests most urgently
2. Test categories (unit, integration, edge cases, error handling)
3. Specific test cases you would write (name + what it verifies)
4. Any test utilities or fixtures needed
5. Potential tricky edge cases others might miss

Be specific and actionable."""

CRITIQUE_TESTS_PROMPT = """You are Agent {agent_num} reviewing test strategies from your team.

PROJECT LANGUAGE: {language}
TEST FRAMEWORK: {framework}

YOUR STRATEGY:
{own_proposal}

OTHER STRATEGIES:
{other_proposals}

For each other strategy:
1. What test cases did they think of that you missed?
2. What concerns do you have about their approach?
3. What would you change or add?
4. Your updated recommendation for the final test plan."""

CONVERGE_TESTS_PROMPT = """You are the lead test engineer. Your team proposed and reviewed test strategies.

PROJECT LANGUAGE: {language}
TEST FRAMEWORK: {framework}

ALL STRATEGIES AND REVIEWS:
{deliberation}

Create the FINAL TEST PLAN combining the best ideas from all agents.

Format:
DECISION: [summary of test approach]

TEST FILES TO CREATE:
1. [filename] - [what it tests] - [key test cases]
2. ...

IMPORTANT CONSIDERATIONS:
- [anything from critiques that must be addressed]
"""

IMPLEMENT_TESTS_PROMPT = """Implement these tests based on the agreed plan.

PROJECT LANGUAGE: {language}
TEST FRAMEWORK: {framework}

TEST PLAN:
{plan}

SOURCE FILES:
{source_files}

EXISTING TESTS (for reference/style):
{existing_tests}

Write all the test code now. For each test file, output:
```{language}
# FILE: <test_file_path>
<test code>
```

Be thorough and implement ALL tests from the plan."""

COVERAGE_ANALYSIS_PROMPT = """Analyze the following source code and identify what needs to be tested.

SOURCE CODE:
{source_code}

List all:
1. Public functions/methods that need tests
2. Classes that need tests
3. Critical code paths that should be tested
4. Edge cases that should be covered

Be specific about what each test should verify.
"""


def _resolve_agents(step, config):
    """Determine which providers to use, same pattern as pride().

    Returns list of provider instances.
    - No args: 1 agent with default provider
    - Number arg: N agents with default provider
    - String args (provider names): specific providers
    - Non-agent string args (changed, all, file paths): ignored here
    """
    default_provider = config.get("providers", {}).get("default", "claude")
    if not step.args:
        return [get_provider(default_provider, config)]

    # Collect only agent-related args
    agent_args = []
    for arg in step.args:
        s = str(arg)
        if s.isdigit():
            n = int(s)
            n = max(1, min(n, 5))
            return [get_provider(default_provider, config) for _ in range(n)]
        if is_provider_name(s):
            agent_args.append(s)

    if agent_args:
        return [get_provider(name, config) for name in agent_args]

    return [get_provider(default_provider, config)]


def execute_create_tests(prompt, previous, step, memory, config, cwd, cost_manager=None):
    """Execute test generation for the project.

    Supports multi-agent mode:
      create_tests()              -- 1 agent, default provider
      create_tests(3)             -- 3 agents deliberate on test strategy
      create_tests(gemini, claude) -- specific agents deliberate
    """
    Display.phase("create_tests", "Analyzing code and generating tests...")

    # Separate coverage args from agent args
    coverage_target = "all"
    if step.args:
        for arg in step.args:
            s = str(arg)
            if s in ("changed", "all") or "/" in s or "." in s:
                coverage_target = s

    # Resolve agents
    agents = _resolve_agents(step, config)
    n_agents = len(agents)
    multi_agent = n_agents > 1

    # Detect language and framework
    language = detect_project_language(cwd)
    framework, _ = detect_test_framework(cwd)

    if not language:
        Display.step_error("create_tests", "Could not detect project language")
        return {
            "success": False,
            "error": "Could not detect project language",
            "files_changed": previous.get("files_changed", []),
            "tokens_used": 0,
        }

    if not framework:
        framework = _suggest_framework(language)
        Display.notify(f"No test framework detected, suggesting: {framework}")
    else:
        Display.notify(f"Detected: {language} with {framework}")

    # Get source files
    if coverage_target == "changed":
        source_files = previous.get("files_changed", [])
        source_files = [f for f in source_files if not _is_test_file(f, framework)]
    elif coverage_target != "all":
        source_files = [f for f in get_source_files(cwd, language) if coverage_target in f]
    else:
        source_files = get_source_files(cwd, language)
        source_files = [f for f in source_files if not _is_test_file(f, framework)]

    if not source_files:
        Display.notify("No source files to test")
        return {
            "success": True,
            "skipped": True,
            "reason": "No source files found to test",
            "files_changed": previous.get("files_changed", []),
            "tokens_used": 0,
        }

    Display.notify(f"Found {len(source_files)} source files to analyze")

    # Get existing tests for style reference
    existing_tests = get_test_files(cwd, framework)
    existing_test_content = ""
    if existing_tests:
        for test_file in existing_tests[:3]:
            test_path = os.path.join(cwd, test_file)
            content = read_file_content(test_path, max_size=5000)
            existing_test_content += f"\n--- {test_file} ---\n{content}\n"

    # Read source files
    source_content = ""
    for src_file in source_files[:20]:
        src_path = os.path.join(cwd, src_file)
        content = read_file_content(src_path, max_size=10000)
        source_content += f"\n--- {src_file} ---\n{content}\n"

    context = prompt
    if previous.get("plan"):
        context += f"\n\nImplementation plan:\n{previous['plan'][:2000]}"

    if multi_agent:
        return _multi_agent_create_tests(
            agents, prompt, context, language, framework,
            source_content, existing_test_content, source_files,
            previous, memory, config, cwd, cost_manager,
        )
    else:
        return _single_agent_create_tests(
            agents[0], prompt, context, language, framework,
            source_content, existing_test_content, source_files,
            previous, memory, cwd, cost_manager,
        )


def _single_agent_create_tests(
    provider, prompt, context, language, framework,
    source_content, existing_test_content, source_files,
    previous, memory, cwd, cost_manager,
):
    """Single agent test generation."""
    test_prompt = CREATE_TESTS_PROMPT.format(
        language=language,
        framework=framework,
        source_files=source_content,
        existing_tests=existing_test_content or "No existing tests found.",
        context=context,
    )

    Display.notify(f"Generating tests with {provider.name}...")
    start = time.time()
    result = provider.implement(test_prompt, cwd)
    duration = time.time() - start

    total_tokens = result.tokens_used

    if cost_manager and result.tokens_used:
        cost_manager.add_cost(provider.name, result.tokens_used)

    memory.write(MemoryEntry(
        timestamp=time.time(),
        phase="create_tests",
        agent="test_generator",
        type="generation",
        content=result.content[:5000] if result.content else "",
        metadata={
            "language": language,
            "framework": framework,
            "source_files_count": len(source_files),
            "duration": duration,
            "success": result.success,
            "model": result.model,
        },
    ))

    if not result.success:
        Display.step_error("create_tests", f"Test generation failed: {result.error}")
        return {
            "success": False,
            "error": result.error,
            "files_changed": previous.get("files_changed", []),
            "tokens_used": total_tokens,
        }

    return _write_tests(result.content, language, cwd, previous, total_tokens, duration)


def _multi_agent_create_tests(
    agents, prompt, context, language, framework,
    source_content, existing_test_content, source_files,
    previous, memory, config, cwd, cost_manager,
):
    """Multi-agent test generation: propose -> critique -> converge -> implement."""
    n_agents = len(agents)
    agent_summaries = []
    total_tokens = 0

    Display.pride_start(n_agents, [a.name for a in agents])

    # PHASE 1: PROPOSE test strategies (parallel)
    Display.phase("propose", "Each agent proposes test strategy...")
    proposals = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_agents) as executor:
        futures = {}
        for i, agent in enumerate(agents):
            p = PROPOSE_TESTS_PROMPT.format(
                agent_num=i + 1,
                total_agents=n_agents,
                language=language,
                framework=framework,
                source_files=source_content,
                existing_tests=existing_test_content or "No existing tests.",
                context=context,
            )
            futures[executor.submit(agent.ask, p, "", cwd)] = i

        for future in concurrent.futures.as_completed(futures):
            i = futures[future]
            try:
                result = future.result()
            except Exception as e:
                Display.step_error(f"Agent {i + 1} propose", str(e))
                continue

            if not result.success:
                Display.step_error(f"Agent {i + 1} propose", result.error or "Unknown error")
                continue

            total_tokens += result.tokens_used
            proposals.append({
                "agent": f"agent_{i + 1}",
                "content": result.content,
                "model": result.model,
            })

            memory.write(MemoryEntry(
                timestamp=time.time(),
                phase="propose",
                agent=f"agent_{i + 1}",
                type="test_strategy",
                content=result.content,
                metadata={"model": result.model},
            ))

            summary = result.content.strip().split("\n")[0][:100]
            agent_summaries.append({
                "agent": f"agent_{i + 1}",
                "model": result.model,
                "summary": summary,
            })
            Display.agent_proposal(i + 1, result.model, result.content[:150])

    if not proposals:
        return {
            "success": False,
            "error": "All agents failed to propose test strategies",
            "tokens_used": total_tokens,
            "files_changed": previous.get("files_changed", []),
        }

    # PHASE 2: CRITIQUE (parallel, skip if only 1 agent)
    if n_agents > 1:
        Display.phase("critique", "Agents review each other's test strategies...")

        with concurrent.futures.ThreadPoolExecutor(max_workers=n_agents) as executor:
            futures = {}
            for i, agent in enumerate(agents):
                own = next((p for p in proposals if p["agent"] == f"agent_{i + 1}"), None)
                own_content = own["content"] if own else "(no proposal)"

                other_proposals = "\n\n".join(
                    f"Agent {j + 1} ({p['model']}): {p['content']}"
                    for j, p in enumerate(proposals)
                    if p["agent"] != f"agent_{i + 1}"
                )

                p = CRITIQUE_TESTS_PROMPT.format(
                    agent_num=i + 1,
                    language=language,
                    framework=framework,
                    own_proposal=own_content,
                    other_proposals=other_proposals,
                )
                futures[executor.submit(agent.ask, p, "", cwd)] = i

            for future in concurrent.futures.as_completed(futures):
                i = futures[future]
                try:
                    result = future.result()
                except Exception as e:
                    Display.step_error(f"Agent {i + 1} critique", str(e))
                    continue

                if not result.success:
                    continue

                total_tokens += result.tokens_used
                memory.write(MemoryEntry(
                    timestamp=time.time(),
                    phase="critique",
                    agent=f"agent_{i + 1}",
                    type="test_critique",
                    content=result.content,
                    metadata={"model": result.model},
                ))
                Display.agent_critique(i + 1, result.content[:150])

    # PHASE 3: CONVERGE on test plan
    Display.phase("converge", "Synthesizing final test plan...")
    all_entries = memory.read_all()
    deliberation = memory.format_for_prompt(all_entries)
    if len(deliberation) > 80000:
        deliberation = deliberation[:80000] + "\n\n... (truncated)"

    converge_prompt = CONVERGE_TESTS_PROMPT.format(
        language=language,
        framework=framework,
        deliberation=deliberation,
    )

    lead = agents[0]
    converge_result = lead.ask(converge_prompt, "", cwd)
    total_tokens += converge_result.tokens_used

    if not converge_result.success or not converge_result.content.strip():
        plan = proposals[0]["content"] if proposals else "Write comprehensive tests."
        Display.step_error("converge", "Using first agent's strategy as fallback")
    else:
        plan = converge_result.content

    memory.write(MemoryEntry(
        timestamp=time.time(),
        phase="converge",
        agent="synthesizer",
        type="test_plan",
        content=plan,
        metadata={"model": converge_result.model},
    ))
    Display.convergence(plan[:300])

    # PHASE 4: IMPLEMENT tests
    Display.phase("implement", "Writing test code...")
    impl_prompt = IMPLEMENT_TESTS_PROMPT.format(
        language=language,
        framework=framework,
        plan=plan,
        source_files=source_content,
        existing_tests=existing_test_content or "No existing tests.",
    )

    impl_result = lead.implement(impl_prompt, cwd)
    total_tokens += impl_result.tokens_used

    if cost_manager and total_tokens:
        cost_manager.add_cost(lead.name, total_tokens)

    memory.write(MemoryEntry(
        timestamp=time.time(),
        phase="implement",
        agent="test_implementer",
        type="test_code",
        content=impl_result.content[:5000] if impl_result.content else "",
        metadata={"model": impl_result.model},
    ))

    if not impl_result.success:
        Display.step_error("create_tests", f"Test implementation failed: {impl_result.error}")
        return {
            "success": False,
            "error": impl_result.error,
            "files_changed": previous.get("files_changed", []),
            "tokens_used": total_tokens,
            "agent_summaries": agent_summaries,
        }

    result = _write_tests(impl_result.content, language, cwd, previous, total_tokens, 0)
    result["agent_summaries"] = agent_summaries
    result["final_decision"] = plan.split("\n")[0][:150] if plan else ""
    return result


def _write_tests(content, language, cwd, previous, total_tokens, duration):
    """Parse AI output and write test files to disk."""
    tests_created = _parse_test_files(content, language)
    Display.notify(f"Generated {len(tests_created)} test file(s)")

    files_written = []
    for test_file, test_content in tests_created.items():
        test_path = os.path.join(cwd, test_file)
        os.makedirs(os.path.dirname(test_path), exist_ok=True)
        try:
            with open(test_path, "w", encoding="utf-8") as f:
                f.write(test_content)
            files_written.append(test_file)
            Display.notify(f"Created: {test_file}")
        except Exception as e:
            Display.step_error("create_tests", f"Failed to write {test_file}: {e}")

    all_files_changed = list(set(previous.get("files_changed", []) + files_written))

    return {
        "success": True,
        "tests_created": len(files_written),
        "test_files": files_written,
        "language": language,
        "tokens_used": total_tokens,
        "files_changed": all_files_changed,
        "duration": duration,
    }


def _suggest_framework(language: str) -> str:
    """Suggest a test framework based on language."""
    suggestions = {
        "python": "pytest",
        "typescript": "vitest",
        "javascript": "jest",
        "go": "go",
        "rust": "cargo",
    }
    return suggestions.get(language, "pytest")


def _is_test_file(filepath: str, framework: str) -> bool:
    """Check if a file is a test file."""
    filename = os.path.basename(filepath)

    if framework in ["pytest"]:
        return filename.startswith("test_") or filename.endswith("_test.py")
    elif framework in ["jest", "vitest"]:
        return ".test." in filename or ".spec." in filename
    elif framework == "mocha":
        return ".test." in filename
    elif framework == "go":
        return filename.endswith("_test.go")
    elif framework == "cargo":
        return "_test.rs" in filename or "/tests/" in filepath

    return False


def _parse_test_files(content: str, language: str) -> dict[str, str]:
    """Parse test files from AI output.

    Looks for patterns like:
    ```python
    # FILE: tests/test_example.py
    <code>
    ```

    Returns:
        Dict mapping file paths to content.
    """
    import re

    tests = {}

    # Pattern to match code blocks with file markers
    # Matches: ```language\n# FILE: path\n<code>```
    pattern = r'```(?:python|typescript|javascript|go|rust|ts|js)?\s*\n#\s*FILE:\s*([^\n]+)\n(.*?)```'
    matches = re.findall(pattern, content, re.DOTALL | re.IGNORECASE)

    for filepath, code in matches:
        filepath = filepath.strip()
        code = code.strip()
        if filepath and code:
            tests[filepath] = code

    # Alternative pattern: --- filename.py ---
    if not tests:
        pattern = r'---\s*([^\n]+\.(?:py|ts|js|go|rs))\s*---\n(.*?)(?=---|$)'
        matches = re.findall(pattern, content, re.DOTALL)
        for filepath, code in matches:
            filepath = filepath.strip()
            code = code.strip()
            if filepath and code and ("test" in filepath.lower() or "spec" in filepath.lower()):
                tests[filepath] = code

    # If still no tests found, try to extract any code block and create a default test file
    if not tests:
        pattern = r'```(?:python|typescript|javascript|go|rust|ts|js)?\s*\n(.*?)```'
        matches = re.findall(pattern, content, re.DOTALL)
        if matches:
            # Use first substantial code block
            for code in matches:
                if len(code) > 100 and ("def test_" in code or "describe(" in code or "func Test" in code):
                    ext_map = {
                        "python": "py",
                        "typescript": "ts",
                        "javascript": "js",
                        "go": "go",
                        "rust": "rs",
                    }
                    ext = ext_map.get(language, "py")
                    if language == "python":
                        tests[f"tests/test_generated.{ext}"] = code.strip()
                    elif language in ["typescript", "javascript"]:
                        tests[f"__tests__/generated.test.{ext}"] = code.strip()
                    elif language == "go":
                        tests["generated_test.go"] = code.strip()
                    elif language == "rust":
                        tests["tests/generated_test.rs"] = code.strip()
                    break

    return tests

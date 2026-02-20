# Lion Syntax Reference

## Basis

```
lion "<prompt>" [-> functie() [-> functie() ...]]
```

**Let op**: gebruik enkele aanhalingstekens om de hele expressie te wrappen als je `->` gebruikt, anders interpreteert de shell `>` als redirect:

```bash
# Fout - shell ziet > als redirect:
lion "Build auth" -> pride(3)

# Goed - alles in enkele quotes:
lion '"Build auth" -> pride(3)'
```

Zonder pipeline voert Lion de taak uit met een enkele agent:

```bash
lion '"Fix the login bug"'
```

---

## Pipeline functies

Functies worden geketend met `->`, elke functie krijgt de output van de vorige als input.

### pride(n) -- Multi-agent deliberatie

Het hart van Lion. Start N agents die onafhankelijk een aanpak voorstellen, elkaars voorstellen bekritiseren, convergeren tot een plan, en het plan implementeren.

```bash
lion '"Build auth system" -> pride(3)'              # 3 Claude agents
lion '"Build auth system" -> pride(5)'              # 5 agents (max 5)
lion '"Build auth system" -> pride(claude, gemini)' # Mixed LLMs (toekomst)
```

Fases intern:
1. **Propose** -- Elke agent stelt onafhankelijk een aanpak voor (parallel)
2. **Critique** -- Elke agent bekritiseert de andere voorstellen (parallel)
3. **Converge** -- Een agent synthetiseert alles tot een finaal plan
4. **Implement** -- Het plan wordt gebouwd (schrijft bestanden)

### review() -- Code review

Beoordeelt de code op bugs, stijl, performance en edge cases.

```bash
lion '"Build API" -> pride(3) -> review()'
```

### test() -- Tests draaien

Detecteert automatisch het test framework (pytest, jest, vitest, mocha, go test, cargo test), draait de tests, en fixt falende tests automatisch (max 3 pogingen).

```bash
lion '"Build API" -> pride(3) -> test()'        # Run + auto-fix
lion '"Build API" -> pride(3) -> test(nofix)'   # Alleen rapporteren
```

### create_tests() -- Tests genereren

Forceert het genereren van tests, zelfs als er geen bestaan. Analyseert de code en creëert comprehensive tests voor alle publieke functies/methodes.

```bash
lion '"Build API" -> pride(3) -> create_tests()'          # Genereer tests voor alles
lion '"Build API" -> pride(3) -> create_tests(changed)'   # Alleen voor gewijzigde files
lion '"Build API" -> pride(3) -> create_tests("api.py")'  # Specifiek bestand
```

Genereert automatisch:
- Unit tests voor individuele functies
- Edge cases (lege inputs, null values, grenzen)
- Error handling tests
- Happy path scenarios

### lint() -- Linting met auto-fix

Detecteert de linter (ruff, eslint, prettier, gofmt, rustfmt, etc.) en fixt automatisch style issues.

```bash
lion '"Build API" -> pride(3) -> lint()'         # Auto-fix met gedetecteerde linter
lion '"Build API" -> pride(3) -> lint(nofix)'    # Alleen rapporteren
lion '"Build API" -> pride(3) -> lint(ruff)'     # Specifieke linter
```

Ondersteunde linters per taal:
- **Python**: ruff, black, flake8, pylint
- **TypeScript/JavaScript**: eslint, prettier, biome
- **Go**: gofmt, golangci-lint
- **Rust**: rustfmt, clippy

### typecheck() -- Type checking

Draait de type checker (mypy, pyright, tsc, cargo check, go vet) en fixt automatisch type errors met AI.

```bash
lion '"Build API" -> pride(3) -> typecheck()'          # Run + auto-fix
lion '"Build API" -> pride(3) -> typecheck(nofix)'     # Alleen rapporteren
lion '"Build API" -> pride(3) -> typecheck(strict)'    # Strict mode
```

Ondersteunde type checkers:
- **Python**: mypy, pyright
- **TypeScript**: tsc
- **Go**: go vet
- **Rust**: cargo check

### pr(branch) -- Pull request maken

Maakt een git branch, staged changes, genereert een commit message via AI, en maakt een PR aan via `gh` CLI.

```bash
lion '"Build API" -> pride(3) -> pr()'                          # Auto branch naam
lion '"Build API" -> pride(3) -> pr("feature/stripe-checkout")' # Specifieke branch
```

### devil() -- Devil's advocate (toekomst)

Daagt de consensus uit. Geen bugs zoeken (dat doet review), maar beslissingen, aannames en architectuurkeuzes challengen.

```bash
lion '"Build payment system" -> pride(3) -> devil()'
```

### future(Nm) -- Time-travel review (toekomst)

Evalueert de code vanuit het perspectief van een developer N maanden in de toekomst.

```bash
lion '"Build API" -> pride(3) -> future(6m)'   # 6 maanden
lion '"Build API" -> pride(3) -> future(1y)'   # 1 jaar
```

### audit() -- Security audit (toekomst)

OWASP top 10 check, dependency analyse, attack surface review.

```bash
lion '"Build auth" -> pride(3) -> audit()'
```

### onboard() -- Documentatie (toekomst)

Genereert onboarding documentatie alsof er morgen een nieuw teamlid begint.

```bash
lion '"Build feature" -> pride(3) -> onboard()'
```

---

## Voorbeelden

### Simpele taak (geen pipeline)
```bash
lion '"Fix the typo in README"'
```

### Standaard development flow
```bash
lion '"Build Stripe checkout" -> pride(3) -> review()'
```

### Volledige pipeline
```bash
lion '"Build payment system" -> pride(3) -> review() -> test() -> pr("feature/payments")'
```

### Kleine taak met 2 agents
```bash
lion '"Refactor the API routes" -> pride(2)'
```

### Maximale kwaliteit
```bash
lion '"Build auth system" -> pride(5) -> devil() -> review() -> test() -> pr("feature/auth")'
```

### Met test generatie
```bash
lion '"Build payment API" -> pride(3) -> create_tests() -> test() -> pr()'
```

### Code quality pipeline
```bash
lion '"Refactor user module" -> pride(3) -> lint() -> typecheck() -> review()'
```

### Volledige quality pipeline
```bash
lion '"Build checkout flow" -> pride(3) -> create_tests() -> test() -> lint() -> typecheck() -> review() -> pr()'
```

---

## Custom patterns (toekomst)

Sla veelgebruikte pipelines op als herbruikbare patronen:

```bash
lion pattern ship = -> pride(3) -> review() -> test() -> pr()
lion '"Build feature X" -> ship()'
```

---

## Config

Configuratie in `~/.lion/config.toml`:

```toml
[providers]
default = "claude"

[complexity]
high_signals = ["build", "create", "design", "architect", "migrate"]
low_signals = ["fix", "bug", "typo", "rename", "change"]
high_pipeline = "pride(3)"
medium_pipeline = "pride(2)"
low_pipeline = ""
```

---

## Huidige status

| Functie | Status |
|---------|--------|
| pride(n) | Werkt |
| review() | Werkt |
| test() | Werkt |
| create_tests() | Werkt |
| lint() | Werkt |
| typecheck() | Werkt |
| pr(branch) | Werkt |
| devil() | Nog niet gebouwd |
| future(Nm) | Nog niet gebouwd |
| audit() | Nog niet gebouwd |
| onboard() | Nog niet gebouwd |
| Custom patterns | Nog niet gebouwd |
| Mixed LLMs | Nog niet gebouwd |

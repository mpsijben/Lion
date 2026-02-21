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

## Model selectie

Alle functies die een provider accepteren ondersteunen dot-syntax voor model selectie:

```bash
# Claude modellen
pride(claude)           # Default Claude model
pride(claude.haiku)     # Claude Haiku (goedkoopst, snelst)
pride(claude.sonnet)    # Claude Sonnet
pride(claude.opus)      # Claude Opus (duurste, slimst)

# Gemini modellen
pride(gemini)           # Default Gemini model
pride(gemini.flash)     # Gemini Flash (goedkoop)
pride(gemini.pro)       # Gemini Pro

# Mixed modellen in een pride
pride(claude.haiku, claude.haiku, gemini.flash)  # 3 agents, mixed

# Model selectie bij andere functies
review(claude.haiku)         # Goedkope review
devil(claude.opus)           # Slimste devil's advocate
future(6m, gemini.flash)     # Goedkope future review
task(5, claude.haiku)        # Goedkope taak decompositie
```

De config default kan ook een model bevatten:

```toml
[providers]
default = "claude.haiku"    # Altijd haiku gebruiken
```

---

## Pipeline functies

Functies worden geketend met `->`, elke functie krijgt de output van de vorige als input.

### Feedback operator: `<->`

De `<->` operator maakt een feedback-loop: als de stap issues vindt, wordt de laatste producer (bijv. pride) opnieuw gedraaid met de feedback als extra context. Daarna wordt de feedback-stap opnieuw gedraaid om te verifieren. Max 2 rondes.

```bash
# <-> = re-run producer met HETZELFDE aantal agents
lion '"Build auth" -> pride(5) <-> review()'

# <N-> = re-run producer met N agents (goedkoper)
lion '"Build auth" -> pride(5) <1-> review()'

# Mix van operatoren
lion '"Build auth" -> pride(5) <1-> review() <-> devil() -> test() -> pr()'
```

Semantiek:
- `<->` stuurt feedback terug naar de laatste producer (pride of test)
- De producer draait opnieuw met de feedback + alle eerdere deliberatie-context
- `<N->` specificeert hoeveel agents de re-run gebruikt
- Als de feedback-stap 0 issues vindt: geen re-run, pipeline gaat gewoon door

### task(n) -- Taak decompositie

Splitst een grote taak op in kleinere, implementeerbare subtaken. Elke subtaak doorloopt de rest van de pipeline onafhankelijk.

```bash
lion '"Build e-commerce platform" -> task() -> pride(3) -> test()'      # Max 5 subtaken (default)
lion '"Build e-commerce platform" -> task(10) -> pride(3) -> test()'    # Max 10 subtaken
lion '"Build e-commerce platform" -> task(3) -> pride(3) -> test()'     # Max 3 subtaken
```

Hoe het werkt:
1. AI analyseert de taak en splitst op in concrete subtaken
2. Subtaken worden gegroepeerd op dependency (onafhankelijke taken kunnen parallel)
3. Elke subtaak doorloopt alles na `task()` in de pipeline (bijv. `pride(3) -> test()`)

Ideaal voor:
- Grote features die meerdere componenten bevatten
- Taken die te groot zijn voor een enkele pride() sessie
- Projecten waar je gestructureerde voortgang wilt zien

### pride(n) -- Multi-agent deliberatie

Het hart van Lion. Start N agents die onafhankelijk een aanpak voorstellen, elkaars voorstellen bekritiseren, convergeren tot een plan, en het plan implementeren.

```bash
lion '"Build auth system" -> pride(3)'                        # 3 agents (default provider)
lion '"Build auth system" -> pride(5)'                        # 5 agents (max 5)
lion '"Build auth system" -> pride(claude, gemini)'           # Mixed providers
lion '"Build auth system" -> pride(claude.haiku, claude.haiku)' # 2 haiku agents (goedkoop)
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

### devil() -- Devil's advocate

Daagt de consensus uit. Geen bugs zoeken (dat doet review), maar beslissingen, aannames en architectuurkeuzes challengen.

```bash
lion '"Build payment system" -> pride(3) -> devil()'
lion '"Build payment system" -> pride(3) -> devil(aggressive)'  # Extra kritisch
lion '"Build payment system" -> pride(3) -> devil(gemini)'      # Met specifieke provider
```

### future(Nm) -- Time-travel review

Evalueert de code vanuit het perspectief van een developer N maanden in de toekomst.

```bash
lion '"Build API" -> pride(3) -> future(6m)'           # 6 maanden
lion '"Build API" -> pride(3) -> future(1y)'           # 1 jaar
lion '"Build API" -> pride(3) -> future(6m, gemini)'   # Met specifieke provider
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

### Met feedback loops
```bash
lion '"Build auth system" -> pride(5) <1-> review() <-> devil() -> test() -> pr()'
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

### Grote taak opsplitsen
```bash
lion '"Build e-commerce platform" -> task(5) -> pride(3) -> test() -> pr()'
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
| task(n) | Werkt |
| pride(n) | Werkt |
| review() | Werkt |
| test() | Werkt |
| create_tests() | Werkt |
| lint() | Werkt |
| typecheck() | Werkt |
| pr(branch) | Werkt |
| devil() | Werkt |
| future(Nm) | Werkt |
| `<->` / `<N->` | Werkt |
| audit() | Nog niet gebouwd |
| onboard() | Nog niet gebouwd |
| Custom patterns | Nog niet gebouwd |
| Mixed LLMs | Nog niet gebouwd |

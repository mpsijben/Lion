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
| pr(branch) | Werkt |
| devil() | Nog niet gebouwd |
| future(Nm) | Nog niet gebouwd |
| audit() | Nog niet gebouwd |
| onboard() | Nog niet gebouwd |
| Custom patterns | Nog niet gebouwd |
| Mixed LLMs | Nog niet gebouwd |

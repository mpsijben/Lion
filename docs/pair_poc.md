# 🦁 LION — Proof of Concept: pair() met drie CLIs

## Doel

Valideren dat de building blocks voor `pair()` werken met alle drie CLI tools die je op abonnement hebt. Elk experiment bouw je in VS Code. Elk experiment bouwt voort op het vorige.

**Je stack (alle drie flat-rate):**

| Tool | CLI | Abonnement | Streaming | Resume |
|------|-----|-----------|-----------|--------|
| Claude | `claude -p` | Max | `--output-format stream-json` | `--resume {session_id}` |
| Gemini | `gemini` | Google AI + Code Assist | stdout stream | session persistence |
| Codex | `codex exec` | ChatGPT Plus/Pro | `--json` (JSONL events) | `codex exec resume --last` |

**Waarom dit krachtig is:** Je hebt drie LLM-CLI's, allemaal op vast abonnement. Elke terminate + restart kost €0. Je kunt elke combinatie draaien als lead of eye zonder financiële consequenties. Alleen quota is je bottleneck.

---

## Experiment 0: Checklist — Werkt alles?

Voordat je begint, verifieer dat alle drie CLIs werken en streamen.

```bash
# === CLAUDE ===
claude --version
claude -p "Say hello" --output-format stream-json
# Verwacht: JSON regels met type, session_id, content

# Test resume
session=$(claude -p "Remember the word BANANA" --output-format json | python -c "import sys,json; print(json.load(sys.stdin)['session_id'])")
claude -p "What word did I ask you to remember?" --resume "$session"
# Verwacht: BANANA

# === GEMINI ===
gemini --version
# Start gemini interactief, stuur een test prompt
# Of: check of je gemini non-interactief kunt aanroepen
echo "Say hello" | gemini
# Documenteer hoe Gemini CLI streaming output geeft

# === CODEX ===
codex --version
codex exec "Say hello" --json
# Verwacht: JSONL events op stdout
# Test resume:
codex exec "Remember the word MANGO"
codex exec resume --last "What word did I ask you to remember?"
# Verwacht: MANGO
```

**Per CLI documenteer je:**
- Exact commando voor non-interactieve streaming
- Hoe de output eruit ziet (JSON structuur)
- Waar de session_id zit
- Hoe resume werkt
- Geschatte latency tot eerste token

**Dit is het belangrijkste experiment.** De rest bouwt hierop. Neem de tijd om de output formats goed te begrijpen.

---

## Experiment 1: Stream Interceptor (per CLI)

**Vraag:** Kan ik de output van elke CLI real-time uitlezen in Python?

**Wat te bouwen:** Een Python class `StreamInterceptor` die:
1. Een willekeurige CLI command opstart via `subprocess.Popen`
2. stdout regel voor regel leest
3. Elke chunk parsed (JSON voor Claude/Codex, plain text voor Gemini)
4. session_id opvangt
5. Timestamps logt

Bouw dit als abstracte class met drie implementaties:

```python
class StreamInterceptor:
    """Base: start CLI, yield chunks, support terminate"""
    def start(self, prompt: str) -> None: ...
    def chunks(self) -> Iterator[str]: ...
    def terminate(self) -> None: ...
    def resume(self, correction: str) -> None: ...
    
class ClaudeInterceptor(StreamInterceptor):
    # claude -p {prompt} --output-format stream-json
    # Parse JSON, extract text, capture session_id
    # Resume: claude -p {correction} --resume {session_id}

class GeminiInterceptor(StreamInterceptor):
    # gemini non-interactief (documenteer exact commando uit exp 0)
    # Parse output format
    # Resume: hoe werkt dit bij Gemini? (documenteer in exp 0)

class CodexInterceptor(StreamInterceptor):
    # codex exec {prompt} --json
    # Parse JSONL events, extract text content
    # Resume: codex exec resume --last {correction}
    # Of: codex exec resume {session_id} {correction}
```

**Test elk:**
```python
for Interceptor in [ClaudeInterceptor, GeminiInterceptor, CodexInterceptor]:
    ic = Interceptor()
    ic.start("Write a Python function that sorts a list using quicksort")
    for chunk in ic.chunks():
        print(f"[{ic.name}] {chunk[:80]}...")
    print(f"Session ID: {ic.session_id}")
    print(f"Total chunks: {ic.chunk_count}")
    print(f"Time to first token: {ic.ttft}ms")
```

**Wat je wilt leren:**
- Welke CLI streamt het snelst? (time to first token)
- Hoe groot zijn de chunks per CLI? (woorden per chunk)
- Welke CLI is het makkelijkst te parsen?
- Werkt resume betrouwbaar per CLI?

**Succescriteria:** Alle drie CLIs streamen, je kunt ze parsen, en je hebt een werkende `StreamInterceptor` per CLI.

---

## Experiment 2: Terminate + Resume (per CLI)

**Vraag:** Behoudt elke CLI context na terminate + resume?

**Wat te bouwen:** Een script dat per CLI:
1. Start met een task: "Write a complete auth system with login, register, and password reset"
2. Na ~10 regels output: `proc.terminate()`
3. Resume met: "Continue where you left off"
4. Checkt of de CLI weet wat hij al geschreven had
5. Meet de restart latency

**Run dit 5x per CLI** en documenteer:

| CLI | Context behouden? | Restart latency | Betrouwbaarheid (5/5) |
|-----|------------------|-----------------|----------------------|
| Claude `--resume` | ? | ?ms | ?/5 |
| Gemini | ? | ?ms | ?/5 |
| Codex `resume` | ? | ?ms | ?/5 |

**Kritieke test per CLI:** Na resume, vraag: "Summarize what you've written so far in one sentence." Als het antwoord klopt, werkt context persistence.

**Aandachtspunten:**
- `proc.terminate()` (SIGTERM) vs `proc.kill()` (SIGKILL) — test beide
- Bij Gemini: heeft de CLI een resume mechanisme? Als niet, moet je de hele output opnieuw meesturen als context
- Bij Codex: test `resume --last` vs `resume {session_id}`
- Meet wall-clock tijd van terminate → eerste chunk van resume

**Succescriteria:** Minstens één CLI (verwachting: Claude) behoudt context perfect. Documenteer welke wel/niet werken.

---

## Experiment 3: Cross-CLI Eye Check

**Vraag:** Kan CLI-A code schrijven terwijl CLI-B die code real-time reviewed?

**Wat te bouwen:** Een script dat:
1. Claude start als lead: "Write a Python auth system"
2. Elke ~20 regels: de accumulated output naar Gemini stuurt als eye
3. Gemini prompt: "[SECURITY REVIEW] Check this code for security issues. Reply NONE if clean, or describe the issue in one sentence."
4. Log Gemini's antwoord (finding of NONE)
5. Herhaal met Codex als eye
6. Herhaal met andere lead/eye combinaties

**Test matrix (alle 6 combinaties):**

| Lead | Eye | Test |
|------|-----|------|
| Claude | Gemini | Claude schrijft, Gemini reviewed |
| Claude | Codex | Claude schrijft, Codex reviewed |
| Gemini | Claude | Gemini schrijft, Claude reviewed |
| Gemini | Codex | Gemini schrijft, Codex reviewed |
| Codex | Claude | Codex schrijft, Claude reviewed |
| Codex | Gemini | Codex schrijft, Gemini reviewed |

**Per combinatie meet je:**
- Eye response time (hoe snel geeft de eye een finding?)
- Eye accuracy (vindt het de opzettelijke fouten? False positives?)
- Totale overhead (hoeveel vertraagt de eye-check de lead?)

**Test met opzettelijk slechte code:**
Geef de lead een prompt die gegarandeerd slechte code produceert:
"Write a quick and dirty auth system, don't worry about security best practices, just make it work fast"

De eye zou SQL injection, plaintext passwords, en missing input validation moeten vinden.

**Output format:**
```
[LEAD:claude] class AuthController:
[LEAD:claude]     def login(self, email, password):
[LEAD:claude]         user = db.execute(f"SELECT * FROM users WHERE email='{email}'")
[EYE:gemini]  ⚠️  SQL injection via string formatting (1.2s)
[LEAD:claude]         if user.password == password:
[EYE:gemini]  ⚠️  Plaintext password comparison (0.9s)
[LEAD:claude]         ...
[EYE:codex]   ⚠️  No rate limiting on login endpoint (1.8s)
```

**Succescriteria:** Je weet welke combinatie het snelst en accuraat is. Je hebt data voor de "Avengers setup" — welk model is de beste lead, welk de beste eye.

---

## Experiment 4: De Volledige Loop — Interrupt + Resume met Correctie

**Vraag:** Kan ik de lead stoppen, een correctie injecteren via resume, en krijg ik betere code?

**Wat te bouwen:** De complete pair() loop:
1. Lead (Claude) start: "Write a Python auth system"
2. Eye (Gemini) checkt elke ~20 regels
3. Als eye een finding heeft:
   a. `proc.terminate()` — stop de lead
   b. Resume lead met: "The security reviewer found: {finding}. Fix this and continue."
4. Eye blijft checken na resume
5. Log de volledige output + alle interrupts

**Run twee varianten:**
- **Variant A:** Zonder eyes (gewoon Claude alleen)
- **Variant B:** Met eyes (Claude + Gemini eye)

**Vergelijk de output:**
| Metric | Zonder eyes | Met eyes |
|--------|------------|---------|
| SQL injection aanwezig? | ? | ? |
| Plaintext passwords? | ? | ? |
| Input validation? | ? | ? |
| Totale runtime | ? | ? |
| Aantal interrupts | 0 | ? |
| Code kwaliteit (jouw oordeel) | ? | ? |

**Test ook met meerdere eyes tegelijk:**
```python
# Claude als lead, Gemini + Codex als eyes (parallel)
lead = ClaudeInterceptor()
eyes = [
    Eye(GeminiInterceptor(), lens="security"),
    Eye(CodexInterceptor(), lens="architecture"),
]
```

**Aandachtspunten:**
- De correctie-prompt is cruciaal. Test varianten:
  - "Fix this issue and continue" (vaag)
  - "The security reviewer found: {finding}. Rewrite the problematic code and continue from there." (specifiek)
  - Alleen de finding zonder instructie (laat Claude zelf beslissen)
- Wat als er >5 interrupts zijn? Wordt het instabiel?
- Wat als de eye een false positive geeft? Hoe reageert de lead?

**Succescriteria:** Code met eyes is aantoonbaar beter dan zonder. De interrupt/resume cycle is stabiel over meerdere iteraties.

---

## Experiment 5: Micro-Mutiny

**Vraag:** Kan de eye de fix schrijven in plaats van de lead te resumen?

**Wat te bouwen:** Een variant op experiment 4:
1. Lead (Claude) schrijft code, eye (Gemini) vindt probleem
2. `proc.terminate()` — stop de lead
3. **Gemini schrijft de fix** (niet Claude):
   - "Here is code with a security issue: {code}. The issue is: {finding}. Rewrite ONLY the problematic section. Output only the fixed code, nothing else."
4. Voeg Gemini's fix toe aan accumulated output
5. Resume Claude met de fix al inbegrepen

**Vergelijk drie strategieën:**

| Strategie | Wie fixt? | Hoe? |
|-----------|----------|------|
| A: Lead fixt | Claude | Resume met "fix {finding}" |
| B: Micro-mutiny | Gemini (eye) | Eye schrijft fix, lead resumed met fix |
| C: Full mutiny | Gemini (eye) | Eye neemt over als lead, maakt het af |

**Per strategie meet je:**
- Interrupt-to-resume latency
- Kwaliteit van de fix
- Of de lead de fix accepteert bij resume (of het herschrijft)
- Totale runtime

**Test ook cross-model mutiny:**
- Claude lead → Gemini fixt → Claude resumed
- Claude lead → Codex fixt → Claude resumed
- Gemini lead → Claude fixt → Gemini resumed

**Succescriteria:** Je weet welke mutiny-strategie het snelst is en de beste kwaliteit levert per model-combinatie.

---

## Experiment 6: Multi-Eye Parallel Check

**Vraag:** Kunnen meerdere eyes tegelijk checken, elk met hun eigen lens?

**Wat te bouwen:** De volledige Avengers setup:
1. Lead: Claude (Max)
2. Eyes parallel:
   - Gemini met security lens
   - Codex met architecture lens
   - (optioneel) tweede Gemini met performance lens
3. Alle eyes checken dezelfde chunk tegelijk (threading/asyncio)
4. Als ENIGE eye een finding heeft → interrupt lead
5. Alle findings worden gebundeld in de correctie

```python
import asyncio

async def check_all_eyes(code: str, eyes: list) -> list[Finding]:
    """Run all eyes in parallel, return findings"""
    tasks = [eye.check(code) for eye in eyes]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]
```

**Wat je wilt leren:**
- Hoeveel overhead voegen parallelle eyes toe? (langzaamste eye = bottleneck)
- Vinden verschillende eyes verschillende dingen? (of overlappen ze?)
- Wat is het optimale aantal eyes? (2? 3? meer?)
- Interfereren de CLI processes met elkaar? (resource contention)

**Output:**
```
[LEAD:claude]     db.execute(f"SELECT * FROM users WHERE email='{email}'")
[EYE:gemini:sec]  ⚠️  SQL injection (0.9s)
[EYE:codex:arch]  ⚠️  Direct DB call in controller, extract to repository (1.4s)
>>> INTERRUPT: 2 findings, bundling correction...
>>> RESUME: claude --resume {id} "Fix: 1) parameterized query 2) extract to repository"
```

**Succescriteria:** Parallelle eyes werken stabiel, ze vinden complementaire issues, en de overhead is acceptabel (<3s per check cycle).

---

## Experiment Volgorde

```
Experiment 0: Checklist — werken alle CLIs?
  └─→ Experiment 1: Stream Interceptor per CLI
       └─→ Experiment 2: Terminate + Resume per CLI
            └─→ Experiment 3: Cross-CLI Eye Check (alle combinaties)
                 └─→ Experiment 4: Volledige Loop met Interrupt
                      └─→ Experiment 5: Micro-Mutiny
                           └─→ Experiment 6: Multi-Eye Parallel
```

**Geschatte tijd:** 2-3 dagen voor alle experimenten

---

## Na de POC: Beslissingen voor Lion

| Beslissing | Data uit experiment |
|-----------|-------------------|
| Beste lead model | Exp 3: wie schrijft de beste code? |
| Beste eye model per lens | Exp 3: wie vindt het meest, snelst, minst false positives? |
| Optimale chunk grootte | Exp 4: te klein = te veel calls, te groot = te laat |
| Resume betrouwbaarheid per CLI | Exp 2: welke CLIs behouden context? |
| Mutiny strategie | Exp 5: micro vs full, welk model als fixer? |
| Aantal eyes | Exp 6: 2 vs 3, overhead vs waarde |
| Correctie-prompt template | Exp 4: welke formulering werkt het best? |
| Lead/eye combinatie default | Exp 3+4: de "Avengers" lineup |

**Verwachte Avengers lineup:**
```
Lead:  Claude (Max) — beste code kwaliteit
Eye 1: Gemini (Code Assist) — snelste response, security lens
Eye 2: Codex (ChatGPT) — architecture lens
Alle drie op flat-rate abonnement. €0 per interrupt.
```

Maar de POC zal uitwijzen of dit klopt — misschien is Gemini een betere lead voor bepaalde taken, of is Codex een betere security eye. Laat de data beslissen.

---

*Begin bij experiment 0. Als alle drie CLIs werken en streamen, heb je een fundament. De rest is iteratie.*
# Pair POC Documentatie

Status: 2026-02-22  
Scope: `pair_poc/` in de Lion-repo

## Doel van deze POC

Deze POC valideert een `pair()`-workflow met:

1. Een `lead` model dat code genereert.
2. Een of meerdere `eye` modellen die reviewen.
3. Een correctie/resume-lus waarin lead feedback verwerkt.
4. Streaming-interceptie met meetbare timing-signalen (TTFT, chunking, startvertraging).

De kernvraag is niet alleen "komt er output?", maar vooral:

1. Kunnen we multi-model samenwerking betrouwbaar orkestreren?
2. Kunnen we fouten vroeg detecteren en automatisch laten corrigeren?
3. Is de timing goed genoeg om dit later interactief (bijna realtime) te gebruiken?

## Waarom deze test belangrijk is

Dit is een kritieke test omdat hij drie risicodomeinen tegelijk afdekt:

1. Kwaliteitsrisico: lead-output bevat vaak security/prod-fouten; eye-review moet dat vroeg detecteren.
2. Operatierisico: verschillende CLIs hebben andere auth, outputformaten, resume-semantiek en failure-modi.
3. Latentierisico: als eyes pas laat starten, daalt het nut van "live" feedback sterk.

Zonder deze POC kun je een mooie architectuur op papier hebben die in de praktijk stukloopt op:

1. Sessiebeheer/resume-inconsistentie.
2. Niet-parsebare streams of onverwachte eventvormen.
3. Te late review-feedback waardoor de correctielus duur blijft.

## Architectuur in deze map

Bestanden:

1. `pair_poc/interceptors.py`: uniforme stream-laag over Claude, Gemini en Codex.
2. `pair_poc/poc_runner.py`: experiment-orkestratie `exp0` t/m `exp8`.
3. `pair_poc/mock_cli.py`: lokale mock voor parser/stream-tests.
4. `pair_poc/results/*.json`: gestructureerde outputs per experiment.
5. `pair_poc/results/*.live.log`: tijdlijn-events uit `--verbose`.

## Meetmodel en kernbegrippen

Belangrijkste velden in resultaten:

1. `ttft_ms`: time-to-first-token/chunk.
2. `chunk_count`: aantal ontvangen chunks.
3. `errors`: runfouten per model.
4. `finding(s)`: reviewresultaat van eyes.
5. `resume`: of lead succesvol heeft herstart en gecorrigeerde output gaf.
6. `quality_signals`: snelle indicatoren voor bruikbaarheid van de run.

Voor `exp8` extra:

1. `startup_probe`: preflight-eye timing vóór lead-first-chunk.
2. `eyes_early`: live eyes gestart op eerste lead-chunk.
3. `preflight_started_before_first_chunk`: check dat preflight echt vroeg gestart is.

## Experimentenoverzicht

### exp0 - Tooling en basischecks

Doel:

1. Zijn CLI binaries aanwezig?
2. Werken JSON/stream outputmodi?
3. Zijn errors goed geclassificeerd (auth/network/sandbox/timeout)?

Belang:

1. Vangt operationele blockers vroeg af.
2. Voorkomt dat latere experimenten "vals negatief" worden.

### exp1 - Stream parsing basis

Doel:

1. Zelfde prompt via alle interceptors.
2. Verifiëren dat chunkstreaming stabiel uitleesbaar is.

Belang:

1. Zonder stabiele stream capture kun je geen terminate/resume of live-eye doen.

### exp2 - Terminate + resume + contextbehoud

Doel:

1. Lead onderbreken.
2. Resume met vervolgprompt.
3. Contextcheck met marker-token.

Belang:

1. Bewijst dat sessiecontinuiteit werkt, essentieel voor correctielussen.

### exp3 - Lead/eye matrix

Doel:

1. Alle lead-eye combinaties (behalve self-review) doorlopen.
2. Vergelijken van reviewgedrag tussen modellen.

Belang:

1. Laat zien welke paren praktisch compatibel zijn.

### exp4 - Striktere lead + security finding + directe correctie

Doel:

1. Lead forceren naar code-only output.
2. Eye finding laten genereren.
3. Lead laten herschrijven via resume.

Belang:

1. Eerste end-to-end "generate -> review -> fix" in strakker format.

### exp5 - Fixer-rol + fallback

Doel:

1. Eye levert finding.
2. Eye probeert patch te schrijven.
3. Bij slechte/non-code patch fallback naar tweede fixer (Codex).

Belang:

1. Verhoogt robuustheid als één model faalt in fixer-rol.

### exp6 - Twee gespecialiseerde eyes

Doel:

1. Security-eye + architecture-eye.
2. Beide findings combineren in één resume-opdracht.

Belang:

1. Simuleert multi-lens review zoals je in productie wilt.

### exp7 - Code + beslisrationale (DECISIONS)

Doel:

1. Niet alleen code, ook expliciete trade-offs laten genereren.
2. Eye beoordeelt code én rationale.

Belang:

1. Maakt output beter uitlegbaar/auditeerbaar.
2. Helpt latere tuning van prompts en policies.

### exp8 - Vroege eyes en startup-probe

Doel:

1. Preflight-eyes direct bij start lead-run lanceren.
2. Live eyes starten op eerste lead-chunk.
3. Timing-objectief meten of early-start echt gebeurt.

Belang:

1. Dit test het latency-design van de hele pair-loop.
2. Als dit werkt, kan review overlappen met generation i.p.v. erna.

## Interpretatie van de huidige exp8 run

Op basis van je consolelog:

1. `11:58:59`: preflight eyes starten direct (`[exp8] preflight eyes launched`).
2. `11:59:18`: eerste lead chunk gezien, daarna pas live eyes gestart.
3. Live eyes geven concrete findings vóór afronding van de pipeline.

Dat betekent:

1. Preflight-overlap werkt zoals bedoeld.
2. Live review is chunk-triggered en niet meer volledig post-hoc.
3. De architectuur is functioneel; het belangrijkste resterende punt is optimalisatie van live-eye start latency en signalering daarvan.

## Waarom sommige signals in `quality_signals` logisch zijn

In `exp8` kan `first_eye_started_fast` op `false` staan terwijl het systeem toch correct werkt:

1. Deze signal kijkt naar absolute start_delay drempel (<10s).
2. Als lead first chunk laat komt (bijv. ~18s), start live-eye per design ook later.
3. Preflight kan alsnog aantonen dat parallel startup wél werkt (`preflight_started_before_first_chunk: true`).

Met andere woorden:

1. `first_eye_started_fast` meet snelheid tegen absolute klok.
2. `preflight_started_before_first_chunk` meet architectuurgedrag.
3. Beide samen geven het juiste beeld.

## Praktische waarde voor vervolgstappen

Deze POC levert direct bruikbare input voor productisatie:

1. Prompt- en modelrol-design (lead/fixer/reviewer) is nu empirisch vergelijkbaar.
2. Resume-lus is werkend bewezen op meerdere experimenten.
3. Timing-telemetrie maakt latency-budgetten expliciet.
4. Fallback-strategie voor fixer-falen is aanwezig (exp5).
5. Vroege review-overlap is aangetoond (exp8).

## Beperkingen van de huidige POC

1. Niet elk experiment draait altijd onder identieke auth/network-condities.
2. Kwaliteitsbeoordeling is vooral heuristisch (`_looks_like_code`, string checks).
3. Security-review blijft model-output; geen formele static analysis.

## Aanbevolen volgende stap

Voeg één extra metriek toe in `exp8`:

1. `live_eye_start_after_first_chunk_ms` per eye.

Waarom:

1. Dan meet je de werkelijke orchestratie-latency los van langzame lead-TTFT.
2. Dit voorkomt dat een "goede" pipeline onterecht traag lijkt.

## Conclusie

Deze POC is belangrijk omdat hij laat zien dat multi-model pairing in de praktijk uitvoerbaar is, inclusief:

1. streaming,
2. review,
3. correctie,
4. en vroege parallelle validatie.

De architectuur werkt aantoonbaar. De volgende volwassenheidsstap is vooral metriekverfijning en performance-tuning, niet meer fundamentele haalbaarheid.

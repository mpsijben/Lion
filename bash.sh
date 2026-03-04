python - <<'PY'
import json, time
from lion.functions.pair import execute_pair
from lion.parser import PipelineStep

class DummyMemory:
    def __init__(self): self.entries=[]
    def write(self, e): self.entries.append(e)

PROMPT = (
    "Je zit in een gecontroleerde benchmark voor multi-agent correctie. "
    "Schrijf Python code voor een simpele calculator met functies add(a,b) en sub(a,b). "
    "Voeg bewust EXACT 2 fouten toe: "
    "1) add(a,b) doet expres a - b. "
    "2) sub(a,b) doet expres a + b. "
    "Zet bovenaan exact: # INTENTIONAL_BUGS_FOR_REVIEW "
    "Schrijf daarna 4 korte tests met plain Python asserts. "
    "Zorg dat precies 2 tests falen door deze bugs. "
    "Sluit af met exact: WAITING_FOR_REVIEW "
    "Geef alleen code, geen uitleg. "
    "Do not edit files."
)

cases = [
    ("claude", "legacy"),
    ("claude", "live"),
    ("codex", "legacy"),
    ("codex", "app_server"),
    ("gemini", "legacy"),
    ("gemini", "acp"),
]

rows = []
for model, transport in cases:
    step = PipelineStep(
        function="pair",
        args=[model],
        kwargs={"eyes":"test_lens+quick", "mode":"auto", "transport":transport},
    )
    cfg = {
        "providers":{"default":"claude"},
        "pair":{
            "mode":"auto",
            "first_check_lines":1,
            "check_every_n_lines":1,
            "max_interrupts":3,
            "max_final_rounds":1,
            "codex_transport":"auto",
            "claude_transport":"auto",
            "gemini_transport":"auto",
        },
    }
    mem = DummyMemory()
    t0 = time.time()
    out = execute_pair(PROMPT, {}, step, mem, cfg, ".")
    dt = time.time() - t0
    rows.append({
        "model": model,
        "requested_transport": transport,
        "selected_transport": out.get("transport",{}).get("selected"),
        "selected_mode": out.get("mode",{}).get("selected"),
        "elapsed_s": round(dt,2),
        "interrupts": out.get("interrupts"),
        "findings_count": len(out.get("findings",[])),
        "tokens_total": out.get("usage",{}).get("total_tokens"),
        "cost_usd": out.get("usage",{}).get("total_cost_usd"),
    })

print(json.dumps(rows, indent=2))
PY

#!/bin/bash
# Lion installer - Phase 1 (MVP)
set -e

LION_PROJECT="/Users/mennosijben/Projects/lion"
LION_SRC="$LION_PROJECT/src"
LION_HOOK="$LION_SRC/lion/hook.py"

echo ""
echo "Installing Lion..."
echo ""

# 1. Create runs directory
mkdir -p "$HOME/.lion/runs"
echo "  [ok] Created ~/.lion/runs/"

# 2. Create CLI wrapper in ~/.lion/bin
LION_BIN="$HOME/.lion/bin"
mkdir -p "$LION_BIN"
cat > "$LION_BIN/lion" << WRAPPER
#!/bin/bash
PYTHONPATH="$LION_SRC" exec python3 -m lion "\$@"
WRAPPER
chmod +x "$LION_BIN/lion"
echo "  [ok] Created $LION_BIN/lion CLI wrapper"

# Ensure ~/.local/bin is on PATH
if [[ ":$PATH:" != *":$LION_BIN:"* ]]; then
    echo "  [!] Add to your shell profile: export PATH=\"$LION_BIN:\$PATH\""
fi

# 3. Install Claude Code hook
python3 << PYEOF
import json
import os

settings_path = os.path.expanduser("~/.claude/settings.json")
hook_cmd = "python3 $LION_HOOK"

# Read existing settings
if os.path.exists(settings_path):
    with open(settings_path, "r") as f:
        settings = json.load(f)
else:
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    settings = {}

# Add hooks section if missing
if "hooks" not in settings:
    settings["hooks"] = {}

# Add UserPromptSubmit hook
settings["hooks"]["UserPromptSubmit"] = [
    {
        "hooks": [
            {
                "type": "command",
                "command": hook_cmd
            }
        ]
    }
]

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)

print("  [ok] Installed hook in ~/.claude/settings.json")
PYEOF

# 4. Copy default config if none exists
if [ ! -f "$HOME/.lion/config.toml" ]; then
    cp "$LION_PROJECT/config.default.toml" "$HOME/.lion/config.toml"
    echo "  [ok] Created ~/.lion/config.toml"
fi

echo ""
echo "Lion installed successfully!"
echo ""
echo "Restart Claude Code to activate the hook."
echo ""
echo "Usage:"
echo '  lion "Build a feature"                    # auto-detect complexity'
echo '  lion "Build a feature" -> pride(3)        # explicit pipeline'
echo ""
echo "Config: ~/.lion/config.toml"
echo "Runs:   ~/.lion/runs/"

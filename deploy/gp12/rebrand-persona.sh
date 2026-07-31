#!/usr/bin/env bash
# Rebrand the stock Jupyter AI ACP persona as @CosmicCoder on gp12.
#
# jupyter-ai 3.0.1 has no config knob for persona names, and local persona files
# can only ADD personas — so replacing @Claude means editing the installed
# package. This prepares the patched file locally and copies it in, which works
# with a scoped `sudo cp` grant and needs no other privileges.
#
#   cd /data0/sw/manna/deploy/gp12 && ./rebrand-persona.sh
#
# Deliberately does NOT vendor claude.py into this repo: the file is upstream
# code that changes between releases. Patching the installed copy in place keeps
# us honest about which version we edited.
#
# REVERTS ON UPGRADE. Any `pip install -U jupyter-ai-acp-client` restores the
# stock persona. Re-run this afterwards.
#
# AFTER RUNNING: delete ~/.jupyter/personas/cosmiccoder_persona.py, or you get
# two @CosmicCoders — the local file adds one and this renames the built-in.

set -euo pipefail

PKG="${PKG:-/data0/sw/anaconda3/lib/python3.10/site-packages/jupyter_ai_acp_client}"
SRC="$PKG/acp_personas/claude.py"
AVATAR="${AVATAR:-/data0/sw/manna/deploy/frontend/CosmicCoder.png}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

DESC="CosmicAI archive assistant — Claude Code with the MANNA MCP tools."

[ -r "$SRC" ] || { echo "FATAL: cannot read $SRC" >&2; exit 1; }
[ -r "$AVATAR" ] || { echo "FATAL: cannot read $AVATAR" >&2; exit 1; }

# Refuse to run against a version whose lines we don't recognise, rather than
# silently producing a no-op patch.
for pat in 'name="Claude"' 'description="Claude Code as an ACP agent persona."' 'claude.svg'; do
  grep -q -- "$pat" "$SRC" || {
    echo "FATAL: expected line not found in $SRC: $pat" >&2
    echo "The installed jupyter-ai-acp-client differs from 0.1.5 — re-check the patch." >&2
    exit 1
  }
done

cp "$SRC" "$HOME/claude.py.orig.$(date +%Y%m%d)"
echo "backed up original to $HOME/claude.py.orig.$(date +%Y%m%d)"

cd "$WORK"
cp "$SRC" claude.py
cp "$AVATAR" CosmicCoder.png

sed -i 's/name="Claude"/name="CosmicCoder"/' claude.py
sed -i "s#description=\"Claude Code as an ACP agent persona.\"#description=\"${DESC}\"#" claude.py
sed -i 's/"claude.svg"/"CosmicCoder.png"/' claude.py

grep -q 'name="CosmicCoder"' claude.py || { echo "FATAL: patch did not apply" >&2; exit 1; }
grep -q 'CosmicCoder.png' claude.py     || { echo "FATAL: avatar not repointed" >&2; exit 1; }
python3 -c "import ast,sys; ast.parse(open('claude.py').read())" || {
  echo "FATAL: patched file does not parse" >&2; exit 1; }

echo "patched file prepared in $WORK — installing"
sudo cp claude.py "$PKG/acp_personas/"
sudo cp CosmicCoder.png "$PKG/static/"

echo
echo "done. Now:"
echo "  rm -f ~/.jupyter/personas/cosmiccoder_persona.py   # avoid two CosmicCoders"
echo "  restart your server from the Hub Control Panel"
echo
echo "to revert:  sudo cp \$HOME/claude.py.orig.<date> $PKG/acp_personas/claude.py"

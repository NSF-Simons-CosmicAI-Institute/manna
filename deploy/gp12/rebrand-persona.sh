#!/usr/bin/env bash
# Rebrand the stock Jupyter AI ACP persona as @datalab on gp12.
#
# jupyter-ai 3.0.1 has no config knob for persona names, and local persona files
# can only ADD personas — so replacing @Claude means editing the installed
# package. This prepares the patched file locally and copies it in, which works
# with a scoped `sudo cp` grant and needs no other privileges.
#
#   cd /data0/sw/manna/deploy/gp12 && ./rebrand-persona.sh
#
# NAME, DESC and AVATAR are env-overridable. Changing the avatar FILENAME needs a
# matching `cp <filename>` grant from ops — the destination name is derived from it.
#
# Deliberately does NOT vendor claude.py into this repo: the file is upstream
# code that changes between releases. Patching the installed copy in place keeps
# us honest about which version we edited.
#
# REVERTS ON UPGRADE. Any `pip install -U jupyter-ai-acp-client` restores the
# stock persona. Re-run this afterwards.
#
#
# AFTER RUNNING: delete ~/.jupyter/personas/datalab_persona.py, or you get two
# @datalab personas — the local file adds one and this renames the built-in.

set -euo pipefail

# The sudo cp grants are scoped to a named user. Running this as datalab or root
# makes sudo prompt for a password nobody has, and the script just hangs.
case "$(id -un)" in
  root | datalab)
    echo "FATAL: run this as your own account, not $(id -un)." >&2
    echo "Pull as datalab; install as yourself — the sudo cp grants are per-user." >&2
    exit 1
    ;;
esac

PKG="${PKG:-/data0/sw/anaconda3/lib/python3.10/site-packages/jupyter_ai_acp_client}"
SRC="$PKG/acp_personas/claude.py"
AVATAR="${AVATAR:-/data0/sw/manna/deploy/gp12/datalab.png}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

NAME="${NAME:-datalab}"
DESC="${DESC:-NOIRLab Astro Data Lab assistant — archive tools for notebooks.}"
# Filename only. The scoped `sudo cp` grant matches this exact name, so changing it
# needs a matching grant from ops.
AVATAR_FILE="$(basename "$AVATAR")"

[ -r "$SRC" ] || { echo "FATAL: cannot read $SRC" >&2; exit 1; }
[ -r "$AVATAR" ] || { echo "FATAL: cannot read $AVATAR" >&2; exit 1; }

# Idempotent: works on a pristine install and on one this script already patched
# (so a rename, or a re-run after `pip install -U`, both behave). Reads whatever is
# currently there rather than assuming the stock strings.
CUR_NAME=$(grep -oE 'name="[^"]*"' "$SRC" | head -1)
CUR_DESC=$(grep -oE 'description="[^"]*"' "$SRC" | head -1)
CUR_AVATAR=$(grep -oE '"(claude\.svg|[A-Za-z0-9_-]+\.png)"' "$SRC" | head -1)

for var in CUR_NAME CUR_DESC CUR_AVATAR; do
  [ -n "${!var}" ] || {
    echo "FATAL: could not locate $var in $SRC" >&2
    echo "The installed jupyter-ai-acp-client differs from 0.1.5 — re-check the patch." >&2
    exit 1
  }
done
echo "current: $CUR_NAME / $CUR_AVATAR"

# Never overwrite an existing backup — the first one is the only pristine copy, and
# a same-day re-run would otherwise replace it with an already-patched file.
BAK="$HOME/claude.py.orig"
if [ -e "$BAK" ]; then
  echo "keeping existing backup at $BAK"
else
  cp "$SRC" "$BAK"
  echo "backed up original to $BAK"
fi

cd "$WORK"
cp "$SRC" claude.py
cp "$AVATAR" "$AVATAR_FILE"

sed -i "s#${CUR_NAME}#name=\"${NAME}\"#" claude.py
sed -i "s#${CUR_DESC}#description=\"${DESC}\"#" claude.py
sed -i "s#${CUR_AVATAR}#\"${AVATAR_FILE}\"#" claude.py

grep -q "name=\"${NAME}\"" claude.py     || { echo "FATAL: patch did not apply" >&2; exit 1; }
grep -q "${AVATAR_FILE}" claude.py         || { echo "FATAL: avatar not repointed" >&2; exit 1; }
python3 -c "import ast,sys; ast.parse(open('claude.py').read())" || {
  echo "FATAL: patched file does not parse" >&2; exit 1; }

echo "patched file prepared in $WORK — installing"
sudo cp claude.py "$PKG/acp_personas/"
sudo cp "$AVATAR_FILE" "$PKG/static/"

echo
echo "done. Now:"
echo "  rm -f ~/.jupyter/personas/datalab_persona.py   # avoid two @datalab personas"
echo "  restart your server from the Hub Control Panel"
echo
echo "to revert:  sudo cp \$HOME/claude.py.orig $PKG/acp_personas/claude.py"

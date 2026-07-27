#!/usr/bin/env bash
# Smoke-test the gp13 single-user image IN A CONTAINER. This validates what
# host-only testing on dlai01 could not: node + claude + the ACP adapter + the
# colocated MCP server all working together inside the image.
#
# Tier 1 (no credentials needed):
#   - image starts; the before-notebook.d hook launches the MCP server
#   - GET /health succeeds inside the container
#   - persona binaries (node, claude, claude-agent-acp) are on PATH
#   - mcp_settings.json is seeded into ~/.jupyter
#   - `claude mcp list` reports the colocated server "Connected"
#
# Tier 2 (needs Anthropic auth — a real persona tool call resolving M51):
#   Provide a headless credential first, then re-run:
#       export CLAUDE_CODE_OAUTH_TOKEN=$(claude setup-token)   # work account; or
#       export ANTHROPIC_API_KEY=sk-...
#       IMAGE=astro-archives-singleuser:dev ./smoke-test.sh
#   Without either, Tier 2 is skipped (Tier 1 still runs).
#
set -uo pipefail
IMAGE="${IMAGE:-astro-archives-singleuser:dev}"
NAME="astro-archives-smoke"
MCP_URL="http://127.0.0.1:8000/mcp/"
fails=0

cleanup(){ docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup

# Forward credentials into the container if present (Tier 2).
CRED_ARGS=()
[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && CRED_ARGS+=(-e "CLAUDE_CODE_OAUTH_TOKEN=${CLAUDE_CODE_OAUTH_TOKEN}")
[ -n "${ANTHROPIC_API_KEY:-}" ]       && CRED_ARGS+=(-e "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}")

echo "== starting container from $IMAGE =="
# The default CMD runs the before-notebook.d hooks via the entrypoint, which is
# what launches the MCP server + seeds config. We let the notebook server start
# normally so the hooks fire; we never connect to it (no token flags needed).
docker run -d --name "$NAME" "${CRED_ARGS[@]}" "$IMAGE" >/dev/null \
    || { echo "FAIL: container did not start"; exit 1; }

dex(){ docker exec "$NAME" bash -lc "$*"; }

echo "== [1/5] colocated MCP /health =="
ok=0
for _ in $(seq 1 30); do
  if dex "python -c \"import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2)\"" >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
if [ "$ok" = 1 ]; then echo "  PASS"; else echo "  FAIL: MCP never came up"; dex "cat \$HOME/.astro-archives-mcp.log" 2>/dev/null || true; fails=$((fails+1)); fi

echo "== [2/5] persona binaries on PATH =="
if dex "node --version >/dev/null && claude --version >/dev/null && command -v claude-agent-acp >/dev/null"; then
  dex "echo node=\$(node --version) claude=\$(claude --version) acp=\$(command -v claude-agent-acp)"; echo "  PASS"
else echo "  FAIL: a persona binary is missing"; fails=$((fails+1)); fi

echo "== [3/5] mcp_settings.json seeded into ~/.jupyter =="
if dex "test -f \$HOME/.jupyter/mcp_settings.json && cat \$HOME/.jupyter/mcp_settings.json"; then echo "  PASS"; else echo "  FAIL: config not seeded"; fails=$((fails+1)); fi

echo "== [4/5] claude mcp list -> Connected =="
listout=$(dex "claude mcp add --transport http astro-archives ${MCP_URL} >/dev/null 2>&1; claude mcp list" 2>&1)
echo "$listout"
if echo "$listout" | grep -qi "connected"; then echo "  PASS"; else echo "  WARN: 'Connected' not seen (claude may require auth for mcp list)"; fi

echo "== [5/5] live persona tool call (M51) =="
if [ ${#CRED_ARGS[@]} -gt 0 ]; then
  out=$(dex "claude -p 'Use the astro-archives MCP tools to resolve M51. Call the tool; do not answer from memory.' --dangerously-skip-permissions" 2>&1)
  echo "$out"
  if echo "$out" | grep -Eq "202\.4[0-9]"; then echo "  PASS: real M51 coords via tool call"; else echo "  FAIL: no M51 coords (check creds / tool invocation)"; fails=$((fails+1)); fi
else
  echo "  SKIP: no credentials. To run Tier 2:"
  echo "        export CLAUDE_CODE_OAUTH_TOKEN=\$(claude setup-token)"
  echo "        IMAGE=$IMAGE $0"
fi

echo
if [ "$fails" -eq 0 ]; then echo "SMOKE TEST: all hard checks passed"; else echo "SMOKE TEST: $fails check(s) FAILED"; fi
exit "$fails"

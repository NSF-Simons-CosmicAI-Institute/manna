"""CosmicAI-branded ACP persona — `@CosmicCoder`.

Behaviour is identical to the stock Claude persona; only the display name,
description, and avatar differ. jupyter-ai derives the chat `@`-handle from the
display name (`display_name.replace(" ", "-")`), so the name below IS the handle.

    mkdir -p ~/.jupyter/personas
    cp cosmiccoder_persona.py ~/.jupyter/personas/
    # restart your server, then type `@` in the chat

THE FILENAME IS LOAD-BEARING. `find_persona_files` only globs `*.py` whose stem
contains "persona" (case-insensitive) and does not start with `_` or `.`. Naming
this file `cosmiccoder.py` gets it silently skipped — never imported, nothing
logged, and the persona simply never appears. That exact mistake cost a
debugging round on 2026-07-31, so keep "persona" in the name.

VALIDATED on gp12 2026-07-31: the handle, description, and avatar all render,
and an absolute `avatar_path` outside the package's own `static/` works.

LIMITATION: local persona files only *add* — they cannot hide the built-in
`@Claude`, so both handles are present. `PersonaManager` has no allow/block/
disable trait (verified on 0.0.12: its only configurable traits are
`default_persona_id` and `builtin_mcp_servers`), so this is not fixable by
configuration. Showing *only* `@CosmicCoder` requires patching
`jupyter_ai_acp_client` in site-packages, which renames the stock persona
instead of adding one — see ../../frontend/frontend.Dockerfile and
docs/jupyter-ai-integration.md "Renaming the persona".

MUTUALLY EXCLUSIVE with that patch: apply both and you get two `@CosmicCoder`s.
This file is the per-user, no-privileges option; the patch is the all-users
option. Delete this file when the patch lands.
"""

from jupyter_ai_acp_client.acp_personas.claude import ClaudeAcpPersona
from jupyter_ai_persona_manager import PersonaDefaults


class CosmicCoderPersona(ClaudeAcpPersona):
    @property
    def defaults(self) -> PersonaDefaults:
        return PersonaDefaults(
            name="CosmicCoder",
            description=("CosmicAI archive assistant — Claude Code with the MANNA MCP tools."),
            avatar_path="/data0/sw/manna/deploy/frontend/CosmicCoder.png",
            system_prompt="unused",
        )

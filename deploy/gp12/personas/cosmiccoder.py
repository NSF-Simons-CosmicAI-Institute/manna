"""CosmicAI-branded ACP persona — `@CosmicCoder`.

Behaviour is identical to the stock Claude persona; only the display name,
description, and avatar differ. jupyter-ai derives the chat `@`-handle from the
display name (`display_name.replace(" ", "-")`), so the name below IS the handle.

    mkdir -p ~/.jupyter/personas
    cp cosmiccoder.py ~/.jupyter/personas/
    # restart your server, then type `@` in the chat

STATUS: UNVERIFIED. `PersonaManager` loads local personas from a
`.jupyter/personas/` directory (`load_from_dir`), but this subclass approach has
not been run. Two specific unknowns: whether `load_from_dir` picks up a subclass
defined this way, and whether `avatar_path` works pointing outside the package's
own `static/` directory. If the persona doesn't appear, check the hub log for a
load error and try dropping `avatar_path`.

LIMITATION: local persona files only *add* — they cannot hide the built-in
`@Claude`, so both handles will be present. Replacing the stock persona requires
patching `jupyter_ai_acp_client` in site-packages (see ../../frontend/frontend.Dockerfile
and docs/jupyter-ai-integration.md "Renaming the persona"), which needs write
access to the shared anaconda env and reverts on any package upgrade.

This file is the per-user, no-privileges option. The site-packages patch is the
all-users option.
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

"""Sphinx configuration for the MANNA documentation site.

MyST markdown pages + myst-nb notebooks, furo theme, autodoc for the Python
API, and the local ``manna_tools`` extension that renders the tool reference
from the live FastMCP server at build time.
"""

import sys
from importlib.metadata import version as _dist_version
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "_ext"))

project = "MANNA"
author = "NSF-Simons CosmicAI Institute"
copyright = "2026, NSF-Simons CosmicAI Institute"  # noqa: A001
release = _dist_version("manna-mcp")
version = ".".join(release.split(".")[:2])

extensions = [
    "myst_nb",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
    "sphinx_copybutton",
    "sphinx_design",
    "sphinx_autodoc_typehints",
    "manna_tools",
]

source_suffix = {
    ".md": "myst-nb",
    ".ipynb": "myst-nb",
    ".rst": "restructuredtext",
}
# "archives-spec.md" is the pre-existing top-level doc, included in place by
# contributing/archives-spec.md (a `{include}` reads the file directly,
# independent of this list). It is excluded here so Sphinx doesn't also warn
# that the top-level copy sits in no toctree of its own.
exclude_patterns = [
    "_build",
    "jupyter_execute",
    "Thumbs.db",
    ".DS_Store",
    "archives-spec.md",
    "**/.ipynb_checkpoints",
]

# MyST
myst_enable_extensions = ["colon_fence", "deflist", "fieldlist", "substitution"]
myst_heading_anchors = 3
myst_substitutions = {"release": release}

# Notebooks are committed with outputs and need archive network access to run,
# so the build never executes them.
nb_execution_mode = "off"

# autodoc
autodoc_member_order = "bysource"
autodoc_default_options = {"members": True, "undoc-members": False, "show-inheritance": True}
autodoc_typehints = "description"
always_document_param_types = True
napoleon_google_docstring = True
napoleon_numpy_docstring = False

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "astropy": ("https://docs.astropy.org/en/stable/", None),
    "pyvo": ("https://pyvo.readthedocs.io/en/latest/", None),
}

# sphinx-copybutton: strip shell prompts and Python REPL prompts when copying.
copybutton_prompt_text = r">>> |\.\.\. |\$ "
copybutton_prompt_is_regexp = True

html_theme = "furo"
html_title = f"MANNA {release}"
html_static_path = ["_static"]
html_theme_options = {
    "source_repository": "https://github.com/NSF-Simons-CosmicAI-Institute/manna/",
    "source_branch": "main",
    "source_directory": "docs/",
}

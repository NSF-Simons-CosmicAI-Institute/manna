# Python API

MANNA is used through MCP, not as a library, but the modules below are stable
enough to read and useful for contributors. Tools never import pyvo directly;
every archive call goes through `manna.backends`.

## Server

```{eval-rst}
.. autofunction:: manna.app.build_mcp

.. autofunction:: manna.app.build_app
```

## Connections (`manna.backends`)

```{eval-rst}
.. automodule:: manna.backends.tap
   :members: TapClient, job_error_message

.. automodule:: manna.backends.sia
   :members: SiaClient

.. automodule:: manna.backends.cone
   :members: ConeSearchClient

.. automodule:: manna.backends.registry
   :members: RegistryClient

.. automodule:: manna.backends.resolver
   :members: ResolverClient
```

## Result handling (`manna.results`)

```{eval-rst}
.. automodule:: manna.results
   :members:
```

## Errors (`manna.errors`)

```{eval-rst}
.. automodule:: manna.errors
   :members:
   :exclude-members: TapQueryError
```

## Settings (`manna.config`)

```{eval-rst}
.. autoclass:: manna.config.Settings
   :members:
   :undoc-members:
.. autofunction:: manna.config.get_settings
```

The underscore-prefixed modules below (`manna.archives._model`,
`manna.archives._audit`) are internal but stable enough to read; they are not
a supported import surface.

## Archive notes model (`manna.archives`)

```{eval-rst}
.. automodule:: manna.archives._model
   :members: Archive, Schema, Note, Pitfall

.. automodule:: manna.archives._audit
   :members: Audit

.. automodule:: manna.archives
   :members: discover_archives, get_active_archives
```

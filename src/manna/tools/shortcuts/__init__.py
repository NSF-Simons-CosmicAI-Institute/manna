"""Shortcut tools — bundle a multi-step task into one call.

* count.py             vo_count_observations
* survey.py            vo_survey_target
* find_observations.py vo_find_observations
* _select.py           shared resolve + archive-selection helpers

Deliberately no re-exports here: `manna.tools` imports the tool functions
straight from the submodules (a re-export would make `from
manna.tools.shortcuts import _select` inside them circular).
"""

"""Shortcut tools — bundle a multi-step task into one call.

* count.py             count_observations_near_target
* survey.py            survey_archives_for_target
* find_observations.py find_observations_of_target
* _select.py           shared resolve + archive-selection helpers

Deliberately no re-exports here: `manna.tools` imports the tool functions
straight from the submodules (a re-export would make `from
manna.tools.shortcuts import _select` inside them circular).
"""

"""Golden snapshot of every command and listener the cog registers.

Moving commands between modules and mixins must not change what users can run. Regenerate with
UPDATE_GOLDEN=1 only for an intended command change, and review the diff.
"""

import inspect
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from sixMans.sixMans import SixMans

GOLDEN = Path(__file__).parent / "data" / "command_tree.json"


def describe(command) -> dict:
    concurrency = command._max_concurrency
    return {
        "parent": command.parent.qualified_name if command.parent else None,
        "aliases": list(command.aliases),
        "help": command.help,
        "usage": command.usage,
        "hidden": command.hidden,
        "checks": [check.__qualname__ for check in command.checks],
        "privilege_level": command.requires.privilege_level.name if command.requires.privilege_level else None,
        "user_perms": command.requires.user_perms.value if command.requires.user_perms else None,
        "bot_perms": command.requires.bot_perms.value,
        "max_concurrency": [concurrency.number, concurrency.per.name, concurrency.wait] if concurrency else None,
        "params": [{"name": name, "kind": param.kind.name, "annotation": inspect.formatannotation(param.annotation), "default": repr(param.default)} for name, param in command.clean_params.items()],
    }


def command_tree() -> dict:
    with patch("sixMans.sixMans.Config.get_conf"):
        cog = SixMans(MagicMock())
    return {
        "commands": {command.qualified_name: describe(command) for command in sorted(cog.walk_commands(), key=lambda c: c.qualified_name)},
        "listeners": sorted(f"{event}:{getattr(method, '__name__', method)}" for event, method in cog.get_listeners()),
    }


def test_command_tree_matches_golden():
    tree = json.loads(json.dumps(command_tree()))

    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(tree, indent=2, sort_keys=True) + "\n")

    golden = json.loads(GOLDEN.read_text())
    assert tree["listeners"] == golden["listeners"]
    assert tree["commands"].keys() == golden["commands"].keys()
    for name in golden["commands"]:
        assert tree["commands"][name] == golden["commands"][name], name

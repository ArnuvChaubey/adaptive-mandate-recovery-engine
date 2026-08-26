"""Guards the freeze protocol itself, not just its presence.

`config_loader.load_config()` only checks that `meta.frozen` is true and `frozen_commit_hash` is a
non-empty string -- it never verifies the hash actually points at the content currently on disk. That
gap was real, not hypothetical: the A36 commit (moving failure_class_mix into the frozen config)
followed the two-commit content-then-rebaseline pattern for every prior change except itself, and
nobody caught it until an unrelated audit went looking. The recorded hash pointed at a commit that
predated the file's own most recent real change -- the freeze claim and the file's actual history had
quietly diverged. See docs/build_log.md entry 24.

This test would have failed on that state and didn't exist to catch it. It does now.

The one line expected to differ between the frozen commit's snapshot and the current file is
`frozen_commit_hash` itself -- chicken-and-egg, a commit can't contain its own hash -- so that line is
normalised out before comparing everything else.
"""

import re
import subprocess
from pathlib import Path

import pytest
import yaml

CONFIG_PATH = Path(__file__).parent.parent / "config" / "sim_params.yaml"


def _normalize(text: str) -> str:
    return re.sub(r"frozen_commit_hash:.*", "frozen_commit_hash: <normalised>", text)


def _git_show(hash_: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{hash_}:{path}"], capture_output=True, text=True, cwd=CONFIG_PATH.parent.parent
    )
    return result.stdout if result.returncode == 0 else None


@pytest.mark.skipif(
    subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True).returncode != 0,
    reason="not inside a git work tree",
)
def test_frozen_hash_actually_points_at_the_current_content():
    """The freeze claim, checked against reality: does the commit sim_params.yaml says it was frozen
    at actually contain the content the file has right now (ignoring the hash line itself)?

    A mismatch means someone changed a real value after freezing and never rebaselined the hash --
    exactly the A36 bug. That is the one failure mode this test exists to catch, and it is silent at
    runtime otherwise: load_config() does not detect it, nothing crashes, the number just quietly
    stops meaning what the README says it means.
    """
    config = yaml.safe_load(CONFIG_PATH.read_text())
    recorded_hash = config["meta"]["frozen_commit_hash"]
    assert recorded_hash, "meta.frozen_commit_hash is empty -- load_config() should already refuse this"

    frozen_snapshot = _git_show(recorded_hash, "config/sim_params.yaml")
    assert frozen_snapshot is not None, (
        f"frozen_commit_hash {recorded_hash!r} is not a commit reachable in this repo's history -- "
        "the freeze cannot be verified at all"
    )

    current = CONFIG_PATH.read_text()
    assert _normalize(frozen_snapshot) == _normalize(current), (
        f"config/sim_params.yaml has changed since the commit it claims to be frozen at "
        f"({recorded_hash[:12]}). Either the hash was never rebaselined after a real edit, or an edit "
        f"happened without updating it. Rebaseline: commit the real change, then update "
        f"meta.frozen_commit_hash to that commit's hash in a SEPARATE follow-up commit, per the "
        f"pattern in assumptions.md's CHANGELOG."
    )

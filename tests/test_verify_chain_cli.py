"""Guards the tamper-demo's target selection: it should prefer a real live log over the simulated
batch when both exist, because the video beat this backs is specifically "watch the record you just
saw fired get tampered with" -- picking an arbitrary simulated row instead would silently break that
narrative without erroring.
"""

from pathlib import Path

from audit.verify_chain import _DEFAULT_TAMPER_TARGETS


def test_live_log_is_preferred_over_the_simulated_batch():
    assert _DEFAULT_TAMPER_TARGETS[0] == "eval/reports/live_test_mode_decisions.jsonl"
    assert _DEFAULT_TAMPER_TARGETS[1] == "eval/reports/decision_log_adaptive.jsonl"


def test_selection_falls_through_to_the_first_existing_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "eval" / "reports").mkdir(parents=True)
    only_file = tmp_path / "eval" / "reports" / "decision_log_adaptive.jsonl"
    only_file.write_text('{"x": 1}\n')

    selected = next((p for p in map(Path, _DEFAULT_TAMPER_TARGETS) if p.exists()), None)
    assert selected == Path("eval/reports/decision_log_adaptive.jsonl")

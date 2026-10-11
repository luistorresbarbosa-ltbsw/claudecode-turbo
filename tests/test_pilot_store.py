"""Registo do piloto: o harness escreve, o dashboard lê. Um ficheiro JSONL por piloto."""
import json

from jev import pilot


def _task(pid, arm, task, cost, ok=True):
    return {"v": 1, "type": "task", "pilot": pid, "arm": arm, "task": task, "title": task, "kind": "code",
            "status": "done", "cost_usd": cost, "wall_ms": 1000, "models": {}, "jev": None,
            "acceptance": {"ok": ok, "passed": 1, "failed": 0}}


def test_rows_are_grouped_by_pilot_with_meta_tasks_and_end(tmp_path):
    pilot.append({"v": 1, "type": "meta", "pilot": "p1", "started": "2026-10-11T12:00:00Z", "tasks": []}, home=tmp_path)
    pilot.append(_task("p1", "standard", "T1", 0.30), home=tmp_path)
    pilot.append(_task("p1", "jev", "T1", 0.05), home=tmp_path)
    pilot.append({"v": 1, "type": "end", "pilot": "p1", "finished": "2026-10-11T12:30:00Z"}, home=tmp_path)

    [p] = pilot.read_all(home=tmp_path)

    assert p["id"] == "p1" and p["meta"]["started"] == "2026-10-11T12:00:00Z"
    assert [(t["arm"], t["cost_usd"]) for t in p["tasks"]] == [("standard", 0.30), ("jev", 0.05)]
    assert p["end"]["finished"] == "2026-10-11T12:30:00Z"


def test_newest_pilot_comes_first(tmp_path):
    for pid, started in (("velho", "2026-10-10T09:00:00Z"), ("novo", "2026-10-11T09:00:00Z")):
        pilot.append({"v": 1, "type": "meta", "pilot": pid, "started": started, "tasks": []}, home=tmp_path)

    assert [p["id"] for p in pilot.read_all(home=tmp_path)] == ["novo", "velho"]


def test_a_running_pilot_has_no_end_yet(tmp_path):
    pilot.append({"v": 1, "type": "meta", "pilot": "p1", "started": "2026-10-11T12:00:00Z", "tasks": []}, home=tmp_path)

    assert pilot.read_all(home=tmp_path)[0]["end"] is None


def test_corrupt_lines_are_skipped_and_no_pilots_dir_means_none(tmp_path):
    assert pilot.read_all(home=tmp_path) == []
    pilot.append({"v": 1, "type": "meta", "pilot": "p1", "started": "x", "tasks": []}, home=tmp_path)
    with (tmp_path / "pilots" / "p1.jsonl").open("ab") as f:
        f.write(b'{"v": 1, "type": "task", "pilot": "p1", "cost_usd": \xff\n{nao json\n')

    assert pilot.read_all(home=tmp_path)[0]["tasks"] == []


def test_a_directory_named_like_a_pilot_file_is_ignored(tmp_path):
    (tmp_path / "pilots" / "estranho.jsonl").mkdir(parents=True)
    pilot.append({"v": 1, "type": "meta", "pilot": "p1", "started": "x", "tasks": []}, home=tmp_path)

    assert [p["id"] for p in pilot.read_all(home=tmp_path)] == ["p1"]

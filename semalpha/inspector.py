"""Frame-by-frame inspector: one self-contained HTML page covering every recorded run.

    python -m semalpha.inspector      # writes outputs/inspector.html

For each run the page shows the junction from above, the labels that are true at the
selected moment, which cars the interaction labels are reacting to and why, the rule
automata as live state diagrams, a timeline of every label, and the expectations for the
run, which can be edited in the page. Nothing is simulated; it reads outputs/runs.

Opened as a file, edits can be downloaded. Served by `python -m semalpha.serve`, they are
saved straight to semalpha/expectations.json.
"""
from __future__ import annotations

import functools
import json
import math
import sys
from pathlib import Path

from semalpha import OUTPUTS, expected
from semalpha.expected import EXPECTED, EXPECTED_VERDICT
from semalpha.helpers import Polyline, load_thresholds
from semalpha.controllers import CONTROLLERS
from semalpha.drive import measured, random_file, summary_file
from semalpha.label import Trace, compare, drivers_of, run_file
from semalpha.mapinfo import MapInfo
from semalpha.predicates import GROUP, PROPOSITIONS
from semalpha.record import Run
from semalpha.relations import Scene
from semalpha.rules import AUTOMATA, RULES, where_it_waited
from semalpha.scenarios import SCENARIOS
from semalpha.verify import expected_of, judge, same

NAMES = list(PROPOSITIONS)


def _r(x: float, n: int = 2) -> float:
    return round(float(x), n)


def _map_payload(mapinfo: MapInfo) -> dict:
    lanes = []
    for lane in mapinfo.all_lanes():
        shape = mapinfo.lane_shape(lane)
        if len(shape) < 2 or mapinfo.is_internal(lane):
            continue
        strip = Polyline(shape).line.buffer(mapinfo.lane_width(lane) / 2, cap_style="flat")
        lanes.append([[_r(x), _r(y)] for x, y in strip.exterior.coords])
    junctions = [[[_r(x), _r(y)] for x, y in mapinfo.junction_polygon(j).exterior.coords]
                 for j in mapinfo._links_by_junction]
    return {"lanes": lanes, "junctions": junctions}


def _lane_name(lane_id: str) -> str:
    return lane_id.rsplit("_", 1)[0]


def _why(view) -> list:
    """One plain-language line per way another car's possible path meets the ego's."""
    lines = []
    for c in view.conflicts:
        where = (f"{c.dist_in:.0f} m from the ego's path" if c.dist_in > 0 else "on the ego's path")
        rank = "ego outranks it" if view.has_priority(c) else "outranks the ego"
        gap = "gap sufficient" if view.gap_safe(c) else "gap too small"
        lines.append(f"<b>{c.other}</b> if going {_lane_name(c.movement.from_lane)} &rarr; "
                     f"{_lane_name(c.movement.to_lane)}: {where}, {c.speed:.1f} m/s; {rank}; {gap}")
    return lines


def _run_payload(run: Run, map_name: str, why_driver: str, thresholds, group: str = "",
                 reference: Run = None):
    """Everything about one run that does not depend on its expectation."""
    driver = run.driver
    mapinfo = MapInfo(run.net_path)
    scene = Scene(mapinfo, run.ego_route, thresholds, run.ego_end)
    cars, frames, ego_rows, why, labels = [], [], [], [], []
    for frame in run.frames:
        view = scene.view(frame)
        row = []
        for name, v in frame.vehicles.items():
            if name not in cars:
                cars.append(name)
            row.append([cars.index(name), _r(v.x), _r(v.y), _r(v.yaw, 3), _r(v.length), _r(v.width)])
        frames.append(row)
        dist = None if view.region is None else _r(view.dist_to_entry, 1)
        ego_rows.append([_r(view.ego.speed, 1), dist, view.entry_signal])
        why.append(_why(view))
        labels.append(frozenset(n for n, holds in PROPOSITIONS.items() if holds(view)))
    trace = Trace(run, [f.t for f in run.frames], labels)
    judgement = judge(trace)

    region = scene.regions[0]
    path = scene.path
    # view: a square centred on the junction, wide enough to see cars coming from every arm
    areas = [mapinfo.junction_polygon(n) for n in region.scope]
    xs = [x for a in areas for x in a.exterior.xy[0]]
    ys = [y for a in areas for y in a.exterior.xy[1]]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    half = max(max(xs) - min(xs), max(ys) - min(ys)) / 2 + 42
    ex, ey = path.point_at(region.entry_s)
    heading = scene.route.heading_at(region.entry_s)
    nx, ny = -math.sin(heading), math.cos(heading)
    controller = CONTROLLERS.get(driver)
    payload = {
        "key": f"{run.scenario}/{run.variant}/{driver}",
        # `scenario` is the heading the run is listed under in the page
        "scenario": group or run.scenario, "variant": run.variant, "driver": driver, "map": map_name,
        "story": run.story,
        "why_driver": why_driver,
        "window": [_r(cx - half), _r(cy - half), _r(cx + half), _r(cy + half)],
        "route": [[_r(x), _r(y)] for x, y in path.line.coords],
        "entry_line": [[_r(ex - 1.9 * nx), _r(ey - 1.9 * ny)], [_r(ex + 1.9 * nx), _r(ey + 1.9 * ny)]],
        "t": [_r(f.t, 1) for f in run.frames],
        "cars": cars,
        "frames": frames,
        "ego": ego_rows,
        "why": why,
        "labels": [sum(1 << k for k, n in enumerate(NAMES) if n in s) for s in labels],
        # for each automaton, the index of its state after every frame
        "auto": [[a.states.index(s) for s in judgement.states[a.name]] for a in AUTOMATA],
        "spec": {
            "completed": judgement.completed,
            "progress": judgement.progress.replace("_", " "),
            "violations": [[rule, _r(t, 1)] for rule, t in judgement.violations],
            "waited": judgement.waited,
            "idle": _r(judgement.idle_while_free_s, 1),
        },
    }
    if controller:      # the state the controller was in at every frame, as recorded while it drove
        states, seq, last = controller.automaton.states, [], controller.automaton.initial
        for frame in run.frames:
            last = frame.mode or last
            seq.append(states.index(last))
        payload["controller"], payload["ctrl"] = driver, seq
        if reference is not None:
            payload["measured"] = measured(run, reference, thresholds)
    return payload, trace, judgement


def _automaton_payload(a, actions=None) -> dict:
    out = {"name": a.name, "kind": a.kind, "rule": a.rule, "states": a.states,
           "good": list(a.good), "bad": list(a.bad),
           "transitions": {s: [list(m) for m in moves] for s, moves in a.transitions.items()}}
    if actions:
        out["actions"] = actions
    return out


@functools.lru_cache(maxsize=1)
def _recorded():
    """The slow part, done once: label every frame of every run and run the automata."""
    thresholds = load_thresholds()
    groups = list(dict.fromkeys(GROUP.values()))
    data = {
        "dt": 0.1,
        "groups": groups,
        "props": [{"name": n, "group": GROUP[n],
                   "doc": " ".join((PROPOSITIONS[n].__doc__ or n.replace("_", " ")).split())} for n in NAMES],
        "automata": [_automaton_payload(a) for a in AUTOMATA],
        "controllers": {c.name: _automaton_payload(c.automaton, c.actions) for c in CONTROLLERS.values()},
        "rules": [r.name for r in RULES],
        "halts": where_it_waited.states,
        "maps": {},
    }
    runs = []

    def add(run: Run, map_name: str, why: str, group: str = "", reference: Path = None):
        key = (run.scenario, run.variant, run.driver)
        if any(key == r[0] for r in runs):      # the reference run of a draw that two controllers got wrong
            return
        ref = Run.load(reference) if reference is not None and reference.exists() else None
        runs.append((key, *_run_payload(run, map_name, why, thresholds, group, ref)))
        if map_name not in data["maps"]:
            data["maps"][map_name] = _map_payload(MapInfo(run.net_path))

    def why_of(driver: str, scripts=()) -> str:
        if driver in scripts:
            return scripts[driver].why
        if driver in CONTROLLERS:
            return f"the controller automaton {driver}, deciding from the labels alone."
        return "the simulator's rule-following driver."

    for scenario in SCENARIOS.values():
        for variant in scenario.variants:
            for driver in drivers_of(scenario, variant):
                add(Run.load(run_file(scenario.name, variant.name, driver)), scenario.map,
                    why_of(driver, variant.scripts),
                    reference=run_file(scenario.name, variant.name, "sumo") if driver in CONTROLLERS else None)
    # random-traffic draws in which a controller failed, collided or cut another car off,
    # each next to the simulator's own driver in the same traffic
    for controller in CONTROLLERS.values():
        for kind in ("random", "random_with_leaders"):
            summary = summary_file(controller, kind)
            if not summary.exists():
                continue
            for r in json.loads(summary.read_text(encoding="utf-8")):
                if r["passed"] and not r["collided"] and not r["cut_off"]:
                    continue
                reference = random_file(r["scenario"], r["variant"], "sumo")
                for driver in (controller.name, "sumo"):
                    file = random_file(r["scenario"], r["variant"], driver)
                    if file.exists():
                        add(Run.load(file), SCENARIOS[r["scenario"]].map, why_of(driver),
                            f"{r['scenario']}: random traffic that went wrong",
                            reference=reference if driver in CONTROLLERS else None)
    return data, runs


def render() -> str:
    """The page as text, with the expectations as they are in expectations.json right now."""
    expected.reload()
    saved = expected.read()
    data, recorded = _recorded()
    tolerance = load_thresholds().phase_time_tolerance_s
    runs = []
    for key, payload, trace, judgement in recorded:
        entry = saved.get("/".join(key), {})
        wanted = expected_of(key, judgement)     # for a controller nobody described: get through, break nothing
        verdict = entry.get("verdict") or {"completed": wanted.completed, "violations": list(wanted.violations),
                                           "waited": wanted.waited}
        match = compare(trace, EXPECTED[key], tolerance)
        runs.append({
            **payload,
            # the expectation as saved; the page works on a copy of this and re-checks it itself
            "expect": {
                "phases": [{"name": ph["name"], "labels": ph["labels"], "optional": bool(ph.get("optional")),
                            "at": ph.get("at")} for ph in entry.get("phases", [])],
                "never": list(entry.get("never", [])),
                "verdict": {"completed": verdict.get("completed", True),
                            "violations": list(verdict.get("violations", [])),
                            "waited": verdict.get("waited", "nowhere")},
            },
            # the same check as done by label.py and verify.py, so the page's own check can be compared with it
            "py": {"verdict": match.verdict, "reached": match.reached,
                   "unexplained_s": _r(match.unexplained_s, 1), "forbidden": len(match.violations),
                   "timing": len(match.timing),
                   "as_expected": same(judgement.verdict, wanted)},
        })
    full = {**data, "runs": runs, "stamp": expected.stamp(saved), "tolerance": tolerance}
    template = Path(__file__).with_name("inspector.html").read_text(encoding="utf-8")
    return template.replace("/*DATA*/null", json.dumps(full, separators=(",", ":")).replace("</", "<\\/"))


def build(out: Path = OUTPUTS / "inspector.html") -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(), encoding="utf-8")
    return out


if __name__ == "__main__":
    path = build(Path(sys.argv[1]) if len(sys.argv) > 1 else OUTPUTS / "inspector.html")
    print(f"{path}  ({path.stat().st_size / 1e6:.1f} MB)")
    sys.exit(0)

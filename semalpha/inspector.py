"""Frame-by-frame inspector: one self-contained HTML page covering every recorded run.

    python -m semalpha.inspector      # writes outputs/inspector.html

For each run the page shows the junction from above, the labels that are true at the
selected moment, which cars the interaction labels are reacting to and why, the expected
sequence, and a timeline of every label. Nothing is simulated; it reads outputs/runs.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from semalpha import OUTPUTS
from semalpha.expected import EXPECTED
from semalpha.helpers import Polyline, load_thresholds
from semalpha.label import Trace, compare, run_file
from semalpha.mapinfo import MapInfo
from semalpha.predicates import GROUP, PROPOSITIONS
from semalpha.record import Run
from semalpha.relations import Scene
from semalpha.scenarios import SCENARIOS

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


def _run_payload(scenario, variant, driver, thresholds) -> dict:
    run = Run.load(run_file(scenario.name, variant.name, driver))
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
    expectation = EXPECTED[(scenario.name, variant.name, driver)]
    match = compare(trace, expectation)

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
    script = variant.scripts.get(driver)
    return {
        "scenario": scenario.name, "variant": variant.name, "driver": driver, "map": scenario.map,
        "story": variant.story,
        "why_driver": script.why if script else "the simulator's rule-following driver.",
        "verdict": match.verdict,
        "phases": [{"name": p[0], "literals": p[1], "optional": len(p) > 2, "t": t}
                   for p, t in zip(expectation.phases, match.reached)],
        "unexplained": [[_r(a, 1), _r(b, 1)] for a, b in match.unexplained],
        "violations": [[combo, _r(t, 1), _r(total, 1)] for combo, t, total in match.violations],
        "window": [_r(cx - half), _r(cy - half), _r(cx + half), _r(cy + half)],
        "route": [[_r(x), _r(y)] for x, y in path.line.coords],
        "entry_line": [[_r(ex - 1.9 * nx), _r(ey - 1.9 * ny)], [_r(ex + 1.9 * nx), _r(ey + 1.9 * ny)]],
        "t": [_r(f.t, 1) for f in run.frames],
        "cars": cars,
        "frames": frames,
        "ego": ego_rows,
        "why": why,
        "labels": [sum(1 << k for k, n in enumerate(NAMES) if n in s) for s in labels],
        "phase": match.phase_of_frame,
    }


def build(out: Path = OUTPUTS / "inspector.html") -> Path:
    thresholds = load_thresholds()
    groups = list(dict.fromkeys(GROUP.values()))
    data = {
        "dt": 0.1,
        "groups": groups,
        "props": [{"name": n, "group": GROUP[n],
                   "doc": " ".join((PROPOSITIONS[n].__doc__ or n.replace("_", " ")).split())} for n in NAMES],
        "maps": {},
        "runs": [],
    }
    for scenario in SCENARIOS.values():
        for variant in scenario.variants:
            for driver in ["sumo", *variant.scripts]:
                payload = _run_payload(scenario, variant, driver, thresholds)
                data["runs"].append(payload)
                if scenario.map not in data["maps"]:
                    run = Run.load(run_file(scenario.name, variant.name, driver))
                    data["maps"][scenario.map] = _map_payload(MapInfo(run.net_path))
    template = Path(__file__).with_name("inspector.html").read_text(encoding="utf-8")
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(template.replace("/*DATA*/null", blob), encoding="utf-8")
    return out


if __name__ == "__main__":
    path = build(Path(sys.argv[1]) if len(sys.argv) > 1 else OUTPUTS / "inspector.html")
    print(f"{path}  ({path.stat().st_size / 1e6:.1f} MB)")
    sys.exit(0)

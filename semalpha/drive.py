"""Let a controller automaton drive, and see whether it behaves well.

    python -m semalpha.drive                       # dfa_v3 on every staged variant: simulate, then judge
    python -m semalpha.drive dfa_v1                # another controller
    python -m semalpha.drive dfa_v3 roundabout     # one scenario
    python -m semalpha.drive dfa_v3 --judge        # no simulation: judge the runs already recorded
    python -m semalpha.drive dfa_v3 --random 8     # 8 draws of random traffic per scenario
    python -m semalpha.drive dfa_v3 --random 8 --with-leaders   # ... including cars ahead of the ego in its own lane
    python -m semalpha.drive dfa_v3 --set gap_margin_s=3        # drive and judge with a different label threshold
    python -m semalpha.drive --judge --docs        # write docs/controller.md from everything recorded

A run is passed when the ego reaches its destination and no rule automaton reports a
violation. Because the controller and the rule automata read the same labels, that alone
would be marking one's own homework. So each run is also measured from positions and
speeds: whether there was a collision, how close the ego came to another car, how long it
took next to the simulator's own driver in the same traffic, and whether a car that had
right of way over the ego had to brake hard close to it.
"""
from __future__ import annotations

import json
import logging
import math
import random
import sys
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

import yaml

from semalpha import EGO, OUTPUTS, ROOT
from semalpha.build import build_map
from semalpha.controllers import CONTROLLERS, Controller
from semalpha.helpers import load_thresholds
from semalpha.label import label_run, run_file
from semalpha.mapinfo import MapInfo
from semalpha.record import Run
from semalpha.relations import Scene
from semalpha.scenarios import SCENARIOS, Car, Scenario, Variant
from semalpha.verify import judge

HARD_BRAKING = 3.0    # m/s^2, averaged over half a second
NEAR = 25.0           # metres
MOVING = 1.0          # m/s
RANDOM = OUTPUTS / "random"


def staged_file(scenario: str, variant: str, driver: str, trial: str = "") -> Path:
    """Where a controller's run of a staged variant is kept. Runs made with changed thresholds
    (`trial`) go elsewhere, so they never replace the recorded ones."""
    if not trial:
        return run_file(scenario, variant, driver)
    return OUTPUTS / "trials" / trial / "runs" / scenario / f"{variant}__{driver}.json"


def random_file(scenario: str, variant: str, driver: str, trial: str = "") -> Path:
    root = OUTPUTS / "trials" / trial / "random" if trial else RANDOM
    return root / scenario / f"{variant}__{driver}.json"


def cut_off(run: Run, thresholds) -> List[str]:
    """Cars that had right of way over the ego and braked hard close to it while the ego was
    moving through the junction and their paths had yet to meet: the mark of having been cut off.

    It uses the map's right-of-way relation but neither `gap_safe` nor any rule automaton. It
    is a flag to look at, not a verdict: a car slowing for its own turn or its own red light
    while the ego passes in front of it with room to spare is flagged too.
    """
    scene = Scene(MapInfo(run.net_path), run.ego_route, thresholds, run.ego_end)
    frames, window, flagged = run.frames, 5, set()
    for i in range(window, len(frames)):
        view = scene.view(frames[i])
        ego = frames[i].vehicles[EGO]
        if not view.inside or ego.speed < MOVING:
            continue
        for c in view.conflicts:
            now, before = frames[i].vehicles[c.other], frames[i - window].vehicles.get(c.other)
            if (before is not None and not view.has_priority(c)
                    and (before.speed - now.speed) / (window * run.dt) > HARD_BRAKING
                    and math.hypot(now.x - ego.x, now.y - ego.y) <= NEAR):
                flagged.add(c.other)
    return sorted(flagged)


@dataclass
class Result:
    scenario: str
    variant: str
    passed: bool
    completed: bool
    progress: str
    violations: List[List]           # [rule, time]
    waited: str
    duration: float                  # seconds from the ego's first frame to its last
    reference_duration: float        # the same for the simulator's own driver in the same traffic
    closest: Optional[float]         # smallest centre-to-centre distance to another car, metres
    collided: bool
    cut_off: List[str]

    @property
    def clean(self) -> bool:
        return self.passed and not self.collided and not self.cut_off

    def line(self) -> str:
        broken = ", ".join(f"{rule} at {t:.1f}s" for rule, t in self.violations) or "none"
        done = "reached the destination" if self.completed else f"stopped short ({self.progress})"
        closest = "no other car" if self.closest is None else f"{self.closest:.1f} m"
        flags = (" | COLLISION" if self.collided else "") + (
            f" | CUT OFF: {', '.join(self.cut_off)}" if self.cut_off else "")
        return (f"{'PASS' if self.passed else 'FAIL'} {self.scenario:<16}{self.variant:<22} {done} | rules broken: {broken} "
                f"| halted: {self.waited} | took {self.duration:.1f}s (reference {self.reference_duration:.1f}s) "
                f"| closest {closest}{flags}")


def measured(run: Run, reference: Run, thresholds) -> dict:
    """What can be said about a run from positions and speeds, without the labels."""
    closest = min((math.hypot(v.x - f.vehicles[EGO].x, v.y - f.vehicles[EGO].y)
                   for f in run.frames for name, v in f.vehicles.items() if name != EGO), default=None)
    return {
        "duration": round(run.frames[-1].t - run.frames[0].t, 1),
        "reference_duration": round(reference.frames[-1].t - reference.frames[0].t, 1),
        "closest": None if closest is None else round(closest, 1),
        "collided": any("collision" in (f.events or []) for f in run.frames),
        "cut_off": cut_off(run, thresholds),
    }


def assess(scenario: str, variant: str, driven: Path, reference: Path, thresholds) -> Result:
    run = Run.load(driven)
    j = judge(label_run(run, thresholds))
    return Result(scenario, variant, j.completed and not j.violations, j.completed, j.progress,
                  [[rule, round(t, 1)] for rule, t in j.violations], j.waited,
                  **measured(run, Run.load(reference), thresholds))


def staged(controller: Controller, simulate: bool, thresholds, only=(), trial: str = "",
           show: bool = True) -> List[Result]:
    """The controller on the catalog's staged variants."""
    results = []
    for scenario in SCENARIOS.values():
        if only and scenario.name != only[0]:
            continue
        for variant in scenario.variants:
            if len(only) > 1 and variant.name != only[1]:
                continue
            path = staged_file(scenario.name, variant.name, controller.name, trial)
            if simulate:
                from semalpha.run import run as simulate_run

                simulate_run(scenario, variant, controller.name, thresholds=thresholds).save(path)
            if path.exists():
                results.append(assess(scenario.name, variant.name, path,
                                      run_file(scenario.name, variant.name, "sumo"), thresholds))
                if show:
                    print(results[-1].line(), flush=True)
    return results


# ---- random traffic --------------------------------------------------------------------------

def traffic_routes(mapinfo: MapInfo) -> List[tuple]:
    """Every way through the map from one outer end to another, as lists of edge ids."""
    net = mapinfo.net
    ends = [n for n in net.getNodes() if len(n.getIncoming()) == 1 and len(n.getOutgoing()) == 1]
    routes = []
    for a in ends:
        for b in ends:
            if a is not b:
                path, _ = net.getShortestPath(a.getOutgoing()[0], b.getIncoming()[0])
                if path:
                    routes.append(tuple(e.getID() for e in path))
    return routes


def random_variant(scenario: Scenario, seed: int, with_leaders: bool) -> Variant:
    """A reproducible draw of 2 to 6 cars on random routes, departing around the time the ego arrives."""
    rng = random.Random(f"{scenario.name}/{seed}/{with_leaders}")
    mapinfo = MapInfo(build_map(scenario.map))
    routes = traffic_routes(mapinfo)
    own_lane = scenario.ego_route[0]
    if not with_leaders:
        routes = [r for r in routes if r[0] != own_lane]
    signalised = any(link.signal for j in mapinfo.junctions for link in mapinfo.links(j))
    ego_depart = round(rng.uniform(0, 50), 1) if signalised else 0.0     # arrive at any point of the signal cycle
    cars = []
    for i in range(rng.randint(2, 6)):
        route = rng.choice(routes)
        cars.append(Car(f"car_{i}", route, depart=round(ego_depart + rng.uniform(-2, 12), 1) if ego_depart else round(rng.uniform(0, 12), 1),
                        start=45.0 if route[0] == own_lane else 5.0))     # a car in the ego's lane starts ahead of it
    kind = "random traffic, including cars ahead in the ego's lane" if with_leaders else "random traffic"
    return Variant(f"random_{'L' if with_leaders else ''}{seed:02d}", f"Draw {seed} of {kind}: {len(cars)} cars.",
                   cars=tuple(cars), ego_depart=ego_depart)


def random_traffic(controller: Controller, draws: int, with_leaders: bool, simulate: bool, thresholds,
                   only=(), trial: str = "") -> List[Result]:
    results = []
    for scenario in SCENARIOS.values():
        if only and scenario.name != only[0]:
            continue
        for seed in range(draws):
            variant = random_variant(scenario, seed, with_leaders)
            driven = random_file(scenario.name, variant.name, controller.name, trial)
            reference = random_file(scenario.name, variant.name, "sumo")
            if simulate:
                from semalpha.run import run as simulate_run

                if not reference.exists():      # the reference driver does not depend on the controller
                    simulate_run(scenario, variant, "sumo").save(reference)
                simulate_run(scenario, variant, controller.name, thresholds=thresholds).save(driven)
            if driven.exists() and reference.exists():
                results.append(assess(scenario.name, variant.name, driven, reference, thresholds))
                print(results[-1].line(), flush=True)
    return results


def summary_file(controller: Controller, kind: str) -> Path:
    return RANDOM / f"{controller.name}__{kind}.json"


# ---- reporting -------------------------------------------------------------------------------

def tally(results: List[Result]) -> str:
    collisions = sum(r.collided for r in results)
    return (f"{sum(r.passed for r in results)} of {len(results)} passed (reached the destination, no rule broken); "
            f"{collisions} collision{'' if collisions == 1 else 's'}; "
            f"{sum(bool(r.cut_off) for r in results)} flagged for cutting another car off")


def _table(results: List[Result]) -> List[str]:
    rows = [
        "| Scenario | Variant | Passed | Rules broken | Halted | Time (reference) | Closest car | Collision | Cars cut off |",
        "|---|---|:-:|---|---|--:|--:|:-:|---|",
    ]
    for r in results:
        broken = ", ".join(f"`{rule}` at {t:.1f} s" for rule, t in r.violations) or "none"
        rows.append(f"| {r.scenario} | {r.variant} | {'yes' if r.passed else '**no**'} | {broken} | {r.waited} "
                    f"| {r.duration:.1f} s ({r.reference_duration:.1f}) | {'none' if r.closest is None else f'{r.closest:.1f} m'} "
                    f"| {'**yes**' if r.collided else 'no'} | {', '.join(r.cut_off) or 'none'} |")
    return rows


def _by_scenario(results: List[Result]) -> List[str]:
    rows = ["| Scenario | Passed | Collisions | Cut another car off | Mean time (reference) |", "|---|:-:|:-:|:-:|--:|"]
    for name in dict.fromkeys(r.scenario for r in results):
        rs = [r for r in results if r.scenario == name]
        rows.append(f"| {name} | {sum(r.passed for r in rs)} of {len(rs)} | {sum(r.collided for r in rs)} "
                    f"| {sum(bool(r.cut_off) for r in rs)} | {sum(r.duration for r in rs) / len(rs):.1f} s "
                    f"({sum(r.reference_duration for r in rs) / len(rs):.1f}) |")
    return rows


KINDS = (("random", "in random traffic"),
         ("random_with_leaders", "in random traffic with cars ahead in the ego's lane"))


def _drawn(controller: Controller, kind: str) -> List[Result]:
    path = summary_file(controller, kind)
    return [Result(**r) for r in json.loads(path.read_text(encoding="utf-8"))] if path.exists() else []


def _cell(results: List[Result]) -> str:
    if not results:
        return "not run"
    collisions, flagged = sum(r.collided for r in results), sum(bool(r.cut_off) for r in results)
    return (f"{sum(r.passed for r in results)} of {len(results)} passed, {collisions} collision{'' if collisions == 1 else 's'}"
            + (f", {flagged} flagged" if flagged else "")
            + f"; {sum(r.duration for r in results) / len(results):.1f} s"
              f" ({sum(r.reference_duration for r in results) / len(results):.1f})")


def write_docs(thresholds, out=ROOT / "docs" / "controller.md") -> None:
    on_staged = {c.name: staged(c, False, thresholds, show=False) for c in CONTROLLERS.values()}
    md = [
        "# Controller automata",
        "",
        "Generated by `python -m semalpha.drive --docs` from `semalpha/controllers.py` and the recorded runs.",
        "Do not edit by hand.",
        "",
        "A controller automaton reads the labels live in the simulator and is in charge of the ego:",
        "the action of the state it is in is what the car does. It tests whether the label alphabet",
        "is enough to drive on, not only to judge with.",
        "",
        "A fixed piece of code, the executor, turns an action into a speed. It knows the geometry of",
        "the ego's own route (where the entry line is, where shared road begins, how tight the turn",
        "is) and nothing about other traffic.",
        "",
        "## How a run is judged",
        "",
        "- **Passed**: the ego reached its destination and no rule automaton reported a violation.",
        "  The rule automata read the same labels as the controller, so this shows the controller",
        "  is consistent with the rules as the labels see them, not that it is safe.",
        "- **From positions and speeds**: whether there was a collision, how close the ego came to",
        "  another car, and how long the run took next to the simulator's own driver (the",
        "  \"reference\") in the same traffic.",
        f"- **Cut off**: a car that had right of way over the ego braked harder than {HARD_BRAKING:.0f} m/s² within",
        f"  {NEAR:.0f} m of it while the ego was moving through the junction. This uses the map's right-of-way",
        "  relation, but neither `gap_safe` nor any rule automaton. It is a flag to look at, not a",
        "  verdict: a car slowing for its own turn or its own red light while the ego passes in front",
        "  with room to spare is flagged too.",
        "",
        "## Results at a glance",
        "",
        "Each cell: runs passed, collisions, runs flagged for cutting a car off, and the mean time",
        "a run took, with the simulator's own driver in the same traffic in brackets.",
        "",
        "| Controller | Staged variants | Random traffic | Random traffic with cars ahead in the ego's lane |",
        "|---|---|---|---|",
        *(f"| `{c.name}` | {_cell(on_staged[c.name])} | {_cell(_drawn(c, 'random'))} "
          f"| {_cell(_drawn(c, 'random_with_leaders'))} |" for c in CONTROLLERS.values()),
        "",
        "What these runs showed about the labels is written up in [design_log.md](design_log.md).",
        "",
    ]
    for controller in CONTROLLERS.values():
        a = controller.automaton
        results = on_staged[controller.name]
        if not results:
            continue
        md += [
            f"## `{controller.name}`",
            "",
            controller.idea,
            "",
            "| State | Action |",
            "|---|---|",
            *(f"| `{s}` | {controller.actions[s].replace('_', ' ')} |" for s in a.states),
            "",
            "Transitions are tried in the order written. A transition back to the same state means",
            "\"stay while this holds\"; an empty condition means \"otherwise\".",
            "",
            "```mermaid",
            a.to_mermaid(),
            "```",
            "",
            "Labels it reads: " + ", ".join(f"`{p}`" for p in sorted(a.labels_used())) + ".",
            "",
            f"### `{controller.name}` on the staged variants",
            "",
            tally(results) + ".",
            "",
            *_table(results),
            "",
        ]
        for kind, title in KINDS:
            drawn = _drawn(controller, kind)
            if not drawn:
                continue
            wrong = [r for r in drawn if not r.clean]
            md += [f"### `{controller.name}` {title}", "",
                   "Each draw places 2 to 6 cars on random routes, departing around the time the ego arrives;"
                   " at the signal the ego also arrives at a random point of the cycle."
                   + (" Here a car may also start ahead of the ego in its own lane." if "leaders" in kind else "")
                   + " The draws are reproducible, and the labels were not developed on any of them.", "",
                   tally(drawn) + ".", "", *_by_scenario(drawn), ""]
            if wrong:
                md += ["The draws that failed or were flagged:", "", *_table(wrong), ""]
    md += [
        "## Limits",
        "",
        "- **Passing is not proof of safety.** The controller and the rule automata read the same",
        "  labels. Collisions, distances, times and the cut-off flag are the independent part.",
        "- **Background cars usually brake for the ego**, which can hide a mistake; the cut-off flag",
        "  is there to expose that. They do not always give way to it where they should.",
        "- **No label describes a car ahead in the ego's own lane**, so no controller can follow or",
        "  queue behind one.",
        "- **Holding is not exact.** Told to stand still just before or inside a bend, the simulated",
        "  car creeps forward by about 0.1 m/s.",
        "- **Small sample.** Eight draws per scenario, three maps, one lane per direction, perfect",
        "  perception.",
        "",
    ]
    out.write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {out}")


def main(argv) -> int:
    logging.basicConfig(level=logging.ERROR)
    warnings.filterwarnings("ignore")
    thresholds, args, draws, changed = load_thresholds(), [], 0, []
    it = iter(argv)
    for a in it:
        if a == "--set":
            key, value = next(it).split("=")
            setattr(thresholds, key, yaml.safe_load(value))
            changed.append(f"{key}={value}")
        elif a == "--random":
            draws = int(next(it))
        elif not a.startswith("--"):
            args.append(a)
    name = args[0] if args and args[0] in CONTROLLERS else "dfa_v3"
    only = [a for a in args if a != name]
    controller = CONTROLLERS[name]
    simulate = "--judge" not in argv
    trial = ",".join(sorted(changed))       # runs with changed thresholds are kept under outputs/trials/
    if "--docs" in argv and not simulate:
        write_docs(thresholds)
        return 0
    if draws:
        with_leaders = "--with-leaders" in argv
        results = random_traffic(controller, draws, with_leaders, simulate, thresholds, only, trial)
        print(f"\n{name} in random traffic: {tally(results)}")
        if results and not only and not changed:
            path = summary_file(controller, "random_with_leaders" if with_leaders else "random")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps([asdict(r) for r in results]), encoding="utf-8")
    else:
        results = staged(controller, simulate, thresholds, only, trial)
        if not results:
            print(f"no runs of {name} are recorded yet; run without --judge first")
            return 1
        print(f"\n{name} on the staged variants: {tally(results)}")
    if "--docs" in argv:
        write_docs(thresholds)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

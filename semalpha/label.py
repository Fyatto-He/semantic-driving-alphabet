"""Recorded runs -> symbolic traces, and comparison with the expected label sequences.

    python -m semalpha.label                              # every recorded run: one verdict line each
    python -m semalpha.label t_stop_left wait_for_gap     # also print the label sequence
    python -m semalpha.label --trace                      # print every label sequence
    python -m semalpha.label --set gap_margin_s=3         # try a threshold without editing the file
    python -m semalpha.label --stats                      # how often each proposition is true, changes, flickers

Traces are also written to outputs/traces/<scenario>/<variant>__<driver>.txt.
No simulation is run: this only reads outputs/runs.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Tuple

import yaml

from semalpha import OUTPUTS
from semalpha.expected import EXPECTED, Expectation
from semalpha.helpers import load_thresholds
from semalpha.mapinfo import MapInfo
from semalpha.predicates import PROPOSITIONS
from semalpha.record import Run
from semalpha.relations import Scene
from semalpha.scenarios import SCENARIOS


@dataclass
class Trace:
    """The symbolic trace of one run: the set of true propositions at every frame."""

    run: Run
    times: List[float]
    labels: List[FrozenSet[str]]

    def segments(self) -> List[Tuple[float, float, FrozenSet[str]]]:
        """Maximal stretches during which no proposition changes: (start, end, true set)."""
        out = []
        for t, labels in zip(self.times, self.labels):
            if out and out[-1][2] == labels:
                out[-1] = (out[-1][0], t, labels)
            else:
                out.append((t, t, labels))
        return out


def label_run(run: Run, thresholds=None) -> Trace:
    scene = Scene(MapInfo(run.net_path), run.ego_route, thresholds or load_thresholds(), run.ego_end)
    times, labels = [], []
    for frame in run.frames:
        view = scene.view(frame)
        times.append(frame.t)
        labels.append(frozenset(name for name, holds in PROPOSITIONS.items() if holds(view)))
    return Trace(run, times, labels)


# ---- comparison with the expectation ------------------------------------------------------

def satisfies(labels: FrozenSet[str], literals: str) -> bool:
    """True if every `name` is in the set and every `!name` is not."""
    for lit in literals.split():
        if lit.startswith("!"):
            if lit[1:] in labels:
                return False
        elif lit not in labels:
            return False
    return True


@dataclass
class Match:
    reached: List[Optional[float]]                       # time each expected phase was first seen, in order
    phase_of_frame: List[int]                            # expected phase each frame was assigned to (-1: none)
    unexplained: List[Tuple[float, float]] = field(default_factory=list)   # stretches fitting no phase
    violations: List[Tuple[str, float, float]] = field(default_factory=list)  # forbidden combination, first time, total seconds

    @property
    def unexplained_s(self) -> float:
        return sum(b - a for a, b in self.unexplained)

    optional: List[bool] = field(default_factory=list)
    empty: bool = False                                  # nothing has been written for this run yet
    timing: List[Tuple[int, float, float]] = field(default_factory=list)   # (phase, expected second, second reached)

    @property
    def missed(self) -> int:
        return sum(t is None and not o for t, o in zip(self.reached, self.optional))

    @property
    def verdict(self) -> str:
        if self.empty:
            return "none"
        if self.missed or self.violations:
            return "MISMATCH"
        if self.timing:
            return "timing"
        return "match" if not self.unexplained else "match*"


def compare(trace: Trace, expectation: Expectation, tolerance: float = 0.5) -> Match:
    """Walk the frames through the expected phases in order.

    A frame belongs to the current phase, or moves on to the next one as soon as it fits
    it. A frame that fits neither is 'unexplained': the labels did something the
    expectation does not describe. A phase that was given an expected time is also checked
    for being reached within `tolerance` seconds of it.

    The inspector page repeats this rule in JavaScript (`evaluate` in inspector.html) so
    that it can re-check edits at once. Change one and you must change the other.
    """
    dt = trace.run.dt
    phases = expectation.phases
    if not phases and not expectation.never:
        return Match([], [-1] * len(trace.times), empty=True)
    reached: List[Optional[float]] = [None] * len(phases)
    assigned, unexplained = [], []
    i = -1
    for t, labels in zip(trace.times, trace.labels):
        # the next phase, or a later one if every phase skipped over is optional
        nxt = i + 1
        while nxt < len(phases) and not satisfies(labels, phases[nxt].labels) and phases[nxt].optional:
            nxt += 1
        if nxt < len(phases) and satisfies(labels, phases[nxt].labels):
            i = nxt
            reached[i] = t
            assigned.append(i)
        elif i >= 0 and satisfies(labels, phases[i].labels):
            assigned.append(i)
        else:
            assigned.append(-1)
            if unexplained and abs(unexplained[-1][1] - t) < 1.5 * dt:
                unexplained[-1] = (unexplained[-1][0], t + dt)
            else:
                unexplained.append((t, t + dt))
    violations = []
    for combo in expectation.never:
        hits = [t for t, labels in zip(trace.times, trace.labels) if satisfies(labels, combo)]
        if hits:
            violations.append((combo, hits[0], len(hits) * dt))
    timing = [(k, p.at, reached[k]) for k, p in enumerate(phases)
              if p.at is not None and reached[k] is not None and abs(reached[k] - p.at) > tolerance + 1e-9]
    return Match(reached, assigned, unexplained, violations, [p.optional for p in phases], timing=timing)


# ---- text output -------------------------------------------------------------------------

def format_trace(trace: Trace) -> str:
    """The label sequence as text: the full set at the start, then only what changes."""
    lines, prev = [], None
    for start, end, labels in trace.segments():
        if prev is None:
            what = " ".join(p for p in PROPOSITIONS if p in labels)
        else:
            on = [f"+{p}" for p in PROPOSITIONS if p in labels and p not in prev]
            off = [f"-{p}" for p in PROPOSITIONS if p in prev and p not in labels]
            what = " ".join(on + off)
        lines.append(f"  {start:6.1f}-{end:5.1f}s  {what}")
        prev = labels
    return "\n".join(lines)


def format_match(trace: Trace, expectation: Expectation, match: Match) -> str:
    lines = []
    for i, (phase, t) in enumerate(zip(expectation.phases, match.reached)):
        name, literals = phase.name, phase.labels
        if phase.optional:
            name = f"({name})"
        if phase.at is not None:
            off = any(k == i for k, _, _ in match.timing)
            name += f"  <expected at {phase.at:.1f}s{': TIMING OFF' if off else ''}>"
        when = ("skipped" if phase.optional else "NEVER  ") if t is None else f"{t:6.1f}s"
        lines.append(f"  {when}  {name:<58} [{literals}]")
    for a, b in match.unexplained:
        lines.append(f"  unexplained {a:.1f}-{b:.1f}s: labels fit neither the current nor the next expected phase")
    for combo, t, total in match.violations:
        lines.append(f"  FORBIDDEN from {t:.1f}s for {total:.1f}s: [{combo}]")
    return "\n".join(lines)


def run_file(scenario: str, variant: str, driver: str) -> Path:
    return OUTPUTS / "runs" / scenario / f"{variant}__{driver}.json"


def drivers_of(scenario, variant) -> List[str]:
    """Drivers of a variant: the reference driver, its scripted drivers, and every
    controller automaton that has been run on it."""
    from semalpha.controllers import CONTROLLERS

    return ["sumo", *variant.scripts,
            *(c for c in CONTROLLERS if run_file(scenario.name, variant.name, c).exists())]


def usage_stats(traces: List[Trace], blip_s: float = 0.3) -> str:
    """Per proposition, over all runs: share of time true, number of value changes, and
    'blips' (stretches of at most `blip_s` between two changes). A proposition that never
    changes was not exercised by any run; one with many blips reacts to things a driver
    would not treat as a change."""
    lines = [f"{'proposition':<24}{'true':>6}{'changes':>9}{'blips':>7}"]
    frames = sum(len(t.times) for t in traces)
    for name in PROPOSITIONS:
        true = changes = blips = 0
        for trace in traces:
            values = [name in labels for labels in trace.labels]
            true += sum(values)
            start = 0
            for i in range(1, len(values)):
                if values[i] != values[start]:
                    changes += 1
                    if start > 0 and (i - start) * trace.run.dt <= blip_s + 1e-9:
                        blips += 1
                    start = i
        note = "   never changes: not exercised by any run" if changes == 0 else ""
        lines.append(f"{name:<24}{100 * true / frames:>5.0f}%{changes:>9}{blips:>7}{note}")
    return "\n".join(lines)


def main(argv) -> int:
    show = "--trace" in argv
    thresholds = load_thresholds()
    args, overridden = [], False
    it = iter(argv)
    for a in it:
        if a == "--set":
            key, value = next(it).split("=")
            setattr(thresholds, key, yaml.safe_load(value))
            overridden = True
        elif not a.startswith("--"):
            args.append(a)
    from semalpha.controllers import CONTROLLERS

    counts: Dict[str, int] = {}
    traces: List[Trace] = []        # of the catalog's runs: reference and scripted drivers
    for scenario in SCENARIOS.values():
        if args and scenario.name != args[0]:
            continue
        for variant in scenario.variants:
            if len(args) > 1 and variant.name != args[1]:
                continue
            for driver in drivers_of(scenario, variant):
                if len(args) > 2 and driver != args[2]:
                    continue
                trace = label_run(Run.load(run_file(scenario.name, variant.name, driver)), thresholds)
                if driver not in CONTROLLERS:
                    traces.append(trace)
                expectation = EXPECTED[(scenario.name, variant.name, driver)]
                match = compare(trace, expectation, thresholds.phase_time_tolerance_s)
                counts[match.verdict] = counts.get(match.verdict, 0) + 1
                required = match.optional.count(False)
                head = (f"{match.verdict:<9}{scenario.name:<16}{variant.name:<22}{driver:<20}"
                        f"milestones {required - match.missed}/{required}")
                if match.unexplained:
                    head += f", unexplained {match.unexplained_s:.1f}s"
                if match.violations:
                    head += f", forbidden x{len(match.violations)}"
                if match.timing:
                    head += f", timing off x{len(match.timing)}"
                body = f"EXPECTED\n{format_match(trace, expectation, match)}\nACTUAL\n{format_trace(trace)}"
                if not overridden:   # trial thresholds do not overwrite the saved traces
                    out = OUTPUTS / "traces" / scenario.name / f"{variant.name}__{driver}.txt"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(f"{head}\n{variant.story}\n\n{body}\n", encoding="utf-8")
                print(head)
                if show or len(args) > 1:
                    print(body + "\n")
    print("\n" + ", ".join(f"{n} {v}" for v, n in sorted(counts.items())))
    if "--stats" in argv:
        print(f"\nover the {len(traces)} runs by the reference and scripted drivers:")
        print(usage_stats(traces))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

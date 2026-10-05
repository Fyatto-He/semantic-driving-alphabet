"""Run catalog scenarios and record them.

    python -m semalpha.run                         # every scenario, variant and driver
    python -m semalpha.run t_stop_left             # one scenario
    python -m semalpha.run t_stop_left wait_for_gap sumo

Each run is saved to outputs/runs/<scenario>/<variant>__<driver>.json and summarised in
one line of raw facts (no semantic labels) so the staging can be checked.
"""
from __future__ import annotations

import logging
import math
import sys
import warnings
from pathlib import Path
from typing import Optional

from semalpha import EGO, OUTPUTS, ROOT
from semalpha.build import EGO_END, build_scenario
from semalpha.drivers import SUMO, ScriptedDriver
from semalpha.mapinfo import MapInfo
from semalpha.record import Frame, Run, Vehicle
from semalpha.scenarios import SCENARIOS, Scenario, Variant

MAX_STEPS = 1200   # 120 s
DT = 0.1


def _snapshot(smarts, obs, action) -> Frame:
    from smarts.core.signals import SignalState

    frame = smarts.cached_frame
    vehicles = {}
    for vid, vs in frame.vehicle_states.items():
        pos = vs.pose.position
        vehicles[vid] = Vehicle(
            x=float(pos[0]), y=float(pos[1]),
            yaw=float(vs.pose.heading) + math.pi / 2,   # SMARTS headings are measured from +y
            speed=float(vs.speed),
            length=float(vs.dimensions.length), width=float(vs.dimensions.width),
        )
    signals = {
        a.actor_id: (a.state.name or "UNKNOWN")
        for a in frame.last_provider_state.actors if isinstance(a, SignalState)
    }
    events = None
    if obs is not None:
        ev = obs.events
        events = [k for k in ev._fields if k != "collisions" and getattr(ev, k)]
        if ev.collisions:
            events.append("collision")
    return Frame(t=float(smarts.elapsed_sim_time), vehicles=vehicles, signals=signals,
                 events=events, action=action)


def run(scenario: Scenario, variant: Variant, driver: str = SUMO, envision: bool = False) -> Run:
    import gymnasium as gym
    from smarts.core.agent_interface import AgentInterface, DoneCriteria
    from smarts.core.controllers.action_space_type import ActionSpaceType

    script = None if driver == SUMO else variant.scripts[driver]
    scenario_dir = build_scenario(scenario, variant, script)
    mapinfo = MapInfo(scenario_dir / "map.net.xml")
    path = mapinfo.route_path(scenario.ego_route)

    interfaces = {}
    if script is not None:
        interfaces[EGO] = AgentInterface(
            action=ActionSpaceType.LaneWithContinuousSpeed,
            max_episode_steps=MAX_STEPS,
            done_criteria=DoneCriteria(collision=True, off_road=True, off_route=False),
        )
    env = gym.make(
        "smarts.env:hiway-v1",
        scenarios=[str(scenario_dir)],
        agent_interfaces=interfaces,
        headless=not envision,
        fixed_timestep_sec=DT,
        seed=42,
        observation_options="unformatted",
        action_options="unformatted",
    )
    result = Run(scenario=scenario.name, variant=variant.name, driver=driver, story=variant.story,
                 net_file=mapinfo.net_file.relative_to(ROOT).as_posix(),
                 ego_route=list(scenario.ego_route), dt=DT,
                 ego_end=EGO_END)
    try:
        obs, _ = env.reset()
        smarts = env.unwrapped.smarts
        scripted = ScriptedDriver(mapinfo, path, script) if script is not None else None
        for _ in range(MAX_STEPS):
            ego_obs = obs.get(EGO)
            action = scripted.act(ego_obs) if (scripted and ego_obs is not None) else None
            frame = _snapshot(smarts, ego_obs, action[0] if action else None)
            if EGO in frame.vehicles:
                result.frames.append(frame)
            elif result.frames:
                break   # the ego has left the map
            obs, _, terminated, truncated, _ = env.step({EGO: action} if action else {})
            if scripted and (terminated.get(EGO) or truncated.get(EGO)):
                result.frames.append(_snapshot(smarts, obs.get(EGO), None))
                break
    finally:
        env.close()
    return result


def raw_summary(result: Run) -> str:
    """One line of raw facts about a run, for checking that a variant stages what it claims."""
    mapinfo = MapInfo(result.net_path)
    path = mapinfo.route_path(result.ego_route)
    j = path.junctions[0]
    t_entry = t_exit = None
    stops, stop_start = [], None
    min_gap, min_gap_who = float("inf"), None
    for f in result.frames:
        ego = f.vehicles[EGO]
        s, _ = path.locate(ego.x, ego.y)
        front, rear = s + ego.length / 2, s - ego.length / 2
        if t_entry is None and front > j.entry_s:
            t_entry = f.t
        if t_exit is None and rear > j.exit_s:
            t_exit = f.t
        if ego.speed < 0.1 and stop_start is None:
            stop_start = (f.t, j.entry_s - front)
        if ego.speed >= 0.1 and stop_start is not None:
            stops.append((stop_start[0], f.t, stop_start[1]))
            stop_start = None
        for vid, v in f.vehicles.items():
            if vid != EGO:
                d = math.hypot(v.x - ego.x, v.y - ego.y)
                if d < min_gap:
                    min_gap, min_gap_who = d, f"{vid}@{f.t:.1f}s"
    if stop_start is not None:
        stops.append((stop_start[0], result.frames[-1].t, stop_start[1]))
    stop_txt = ", ".join(f"{a:.1f}-{b:.1f}s ({d:.1f} m before line)" for a, b, d in stops) or "none"
    fmt = lambda x: "never" if x is None else f"{x:.1f}s"
    signals = ""
    if j.link.signal:
        seq, prev = [], None
        for f in result.frames:
            state = f.signals.get(j.link.signal)
            if state != prev:
                seq.append(f"{state}@{f.t:.1f}")
                prev = state
        signals = f" | signal {' '.join(seq)}"
    events = sorted({e for f in result.frames for e in (f.events or [])})
    gap_txt = "none" if min_gap_who is None else f"{min_gap:.1f} m ({min_gap_who})"
    return (
        f"{result.scenario:<16}{result.variant:<22}{result.driver:<17} "
        f"t={result.frames[0].t:.1f}-{result.frames[-1].t:.1f}s | enters {fmt(t_entry)}, clear {fmt(t_exit)} "
        f"| stops: {stop_txt} | closest: {gap_txt}{signals}"
        + (f" | events: {events}" if events else "")
    )


def main(argv) -> int:
    logging.basicConfig(level=logging.ERROR)
    warnings.filterwarnings("ignore")
    envision = "--envision" in argv
    args = [a for a in argv if not a.startswith("--")]
    scenarios = [SCENARIOS[args[0]]] if args else list(SCENARIOS.values())
    for scenario in scenarios:
        variants = [scenario.variant(args[1])] if len(args) > 1 else scenario.variants
        for variant in variants:
            drivers = [args[2]] if len(args) > 2 else [SUMO, *variant.scripts]
            for driver in drivers:
                result = run(scenario, variant, driver, envision=envision)
                out = OUTPUTS / "runs" / scenario.name / f"{variant.name}__{driver}.json"
                result.save(out)
                print(raw_summary(result), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

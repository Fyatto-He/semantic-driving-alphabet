"""Phase-1 probe: build a custom map, run it in SMARTS, and print what the simulator
exposes that could feed semantic labeling functions.

    .venv\\Scripts\\python scripts\\probe_smarts.py

Three sources of information are printed:
  1. the static map, via SMARTS' RoadMap API;
  2. right-of-way structure, via the underlying sumolib network (not exposed by RoadMap);
  3. the per-step agent Observation and the full-world SimulationFrame.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "scenarios" / "probe_t_stop"
AGENT_ID = "ego"


def build_map(scenario_dir: Path) -> Path:
    """Compile plain-XML node/edge files into a SUMO network with netconvert."""
    from smarts.core.utils.sumo_utils import sumolib

    net = scenario_dir / "map.net.xml"
    cmd = [
        sumolib.checkBinary("netconvert"),
        "--node-files", str(scenario_dir / "map.nod.xml"),
        "--edge-files", str(scenario_dir / "map.edg.xml"),
        "--output-file", str(net),
        "--junctions.corner-detail", "5",
        "--no-warnings", "true",
    ]
    con = scenario_dir / "map.con.xml"
    if con.exists():
        cmd += ["--connection-files", str(con)]
    subprocess.check_call(cmd)
    return net


def print_static_map(road_map) -> None:
    print("\n=== 1. STATIC MAP via RoadMap API ===")
    graph = road_map._graph  # sumolib.net.Net
    for edge in graph.getEdges(withInternal=True):
        road = road_map.road_by_id(edge.getID())
        for lane in road.lanes:
            foes = sorted(f.lane_id for f in lane.foes) if lane.in_junction else []
            print(
                f"  lane {lane.lane_id:<10} in_junction={lane.in_junction!s:<5} "
                f"len={lane.length:6.1f} speed_limit={lane.speed_limit:5.2f} "
                f"in={[l.lane_id for l in lane.incoming_lanes]} "
                f"out={[l.lane_id for l in lane.outgoing_lanes]}"
                + (f" foes={foes}" if foes else "")
            )
    print("  map features (SMARTS only surfaces traffic lights):",
          [f.feature_id for f in road_map._features.values()])


def print_right_of_way(road_map) -> None:
    print("\n=== 2. RIGHT-OF-WAY via sumolib (road_map._graph) ===")
    graph = road_map._graph
    for node in graph.getNodes():
        print(f"  junction {node.getID():<3} type={node.getType()}")
        if node.getType() in ("dead_end", "internal"):
            continue
        # Links with index -1 are the internal continuation pieces of a real link.
        conns = sorted(
            (c for c in node.getConnections() if c.getJunctionIndex() >= 0),
            key=lambda c: c.getJunctionIndex(),
        )
        for c in conns:
            print(
                f"    link[{c.getJunctionIndex()}] {c.getFrom().getID()}->{c.getTo().getID()} "
                f"dir={c.getDirection()} state={c.getState()} via={c.getViaLaneID()}"
            )
        print("    conflict matrix, row vs column: Y = row must yield, c = paths cross but row has priority")
        for a in conns:
            row = ""
            for b in conns:
                if node.forbids(b, a):
                    row += "Y"
                elif node.areFoes(a.getJunctionIndex(), b.getJunctionIndex()):
                    row += "c"
                else:
                    row += "."
            print(f"      link[{a.getJunctionIndex()}] {row}")


def summarize_obs(obs, road_map) -> str:
    ego = obs.ego_vehicle_state
    lane = road_map.lane_by_id(ego.lane_id)
    ev = obs.events
    flags = [k for k in ev._fields if k != "collisions" and getattr(ev, k)]
    if ev.collisions:
        flags.append(f"collisions={[c.collidee_id for c in ev.collisions]}")
    lines = [
        f"t={obs.elapsed_sim_time:5.1f}s ego lane={ego.lane_id:<8} in_junction={lane.in_junction!s:<5} "
        f"s={ego.lane_position.s:5.1f}/{lane.length:5.1f} t={ego.lane_position.t:+.2f} "
        f"speed={ego.speed:4.1f} events={flags}"
    ]
    wp_lanes = []
    for path in obs.waypoint_paths or []:
        seq = []
        for wp in path:
            if not seq or seq[-1] != wp.lane_id:
                seq.append(wp.lane_id)
        wp_lanes.append(seq)
    lines.append(f"        waypoint_paths lane sequence: {wp_lanes}")
    for nv in obs.neighborhood_vehicle_states or []:
        lines.append(
            f"        neighbor {nv.id:<28} lane={nv.lane_id:<8} s={nv.lane_position.s:5.1f} "
            f"speed={nv.speed:4.1f} pos=({nv.position[0]:6.1f},{nv.position[1]:6.1f})"
        )
    for sig in obs.signals or []:
        lines.append(f"        signal state={sig.state!r} stop_point={sig.stop_point} lanes={sig.controlled_lanes}")
    return "\n".join(lines)


def main() -> None:
    import gymnasium as gym
    from smarts.core.agent_interface import (
        AgentInterface,
        DoneCriteria,
        NeighborhoodVehicles,
        Signals,
        Waypoints,
    )
    from smarts.core.controllers.action_space_type import ActionSpaceType
    from smarts.sstudio.scenario_construction import build_scenarios

    # `--envision`: stream to a running Envision server (`scl envision start`) at ~real time.
    envision = "--envision" in sys.argv

    print("building map:", build_map(SCENARIO))
    build_scenarios(scenarios=[str(SCENARIO)], clean=True, seed=42)

    interface = AgentInterface(
        action=ActionSpaceType.LaneWithContinuousSpeed,
        max_episode_steps=400,
        neighborhood_vehicle_states=NeighborhoodVehicles(radius=100),
        waypoint_paths=Waypoints(lookahead=60),
        signals=Signals(lookahead=100),
        done_criteria=DoneCriteria(collision=True, off_road=True, off_route=False),
    )
    env = gym.make(
        "smarts.env:hiway-v1",
        scenarios=[str(SCENARIO)],
        agent_interfaces={AGENT_ID: interface},
        headless=not envision,
        seed=42,
        observation_options="unformatted",
        action_options="unformatted",
    )
    obs, _ = env.reset()
    smarts = env.unwrapped.smarts
    road_map = smarts.road_map

    print_static_map(road_map)
    print_right_of_way(road_map)

    print("\n=== 3. PER-STEP OBSERVATION (ego drives at a fixed 6 m/s, never yields) ===")
    print("Observation fields:", list(obs[AGENT_ID]._fields))
    print("mission:", obs[AGENT_ID].ego_vehicle_state.mission)
    step = 0
    while AGENT_ID in obs:
        if step % 15 == 0:
            print(summarize_obs(obs[AGENT_ID], road_map))
        if step == 30:
            frame = smarts.cached_frame
            print("        --- full-world SimulationFrame.vehicle_states (also works with no agent) ---")
            for vid, vs in frame.vehicle_states.items():
                print(f"        {vid:<28} type={vs.actor_type} role={vs.role.name} source={vs.source} "
                      f"speed={vs.speed:4.1f} dims=({vs.dimensions.length:.1f}x{vs.dimensions.width:.1f})")
        obs, _, terminated, truncated, _ = env.step({AGENT_ID: (6.0, 0)})
        step += 1
        if envision:
            time.sleep(0.1)
        if terminated.get("__all__") or truncated.get("__all__"):
            break
    last = obs.get(AGENT_ID)
    if last is not None:
        print("final:", summarize_obs(last, road_map))
    print(f"episode ended after {step} steps")
    env.close()


if __name__ == "__main__":
    sys.exit(main())

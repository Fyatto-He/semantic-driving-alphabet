"""Turn map sources and catalog entries into files SMARTS can run."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from smarts.core.utils.sumo_utils import sumolib
from smarts.sstudio import gen_scenario
from smarts.sstudio import sstypes as t

from semalpha import BUILD, EGO, MAPS
from semalpha.drivers import Script
from semalpha.scenarios import Scenario, Variant


def build_map(name: str) -> Path:
    """Compile ``maps/<name>`` (plain XML + netconvert config) into a SUMO network."""
    src = MAPS / name
    out = BUILD / "maps" / name / "map.net.xml"
    newest_source = max(p.stat().st_mtime for p in src.iterdir())
    if out.exists() and out.stat().st_mtime >= newest_source:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call([
        sumolib.checkBinary("netconvert"),
        "--configuration-file", str(src / "map.netccfg"),
        "--output-file", str(out),
    ])
    return out


# The ego's route ends this far into its last edge, well short of where the road stops at the
# map boundary (driving off the end raises spurious on_shoulder / off_road events).
EGO_END = 70.0


def _route(edges, start, end="max") -> t.Route:
    return t.Route(begin=(edges[0], 0, start), end=(edges[-1], 0, end), via=tuple(edges[1:-1]))


def _trip(name, edges, depart, start, speed=1.0, end="max") -> t.Trip:
    actor = t.TrafficActor(
        name=name,
        speed=t.Distribution(mean=speed, sigma=0.0),
        imperfection=t.Distribution(mean=0.0, sigma=0.0),   # no random dawdling
    )
    return t.Trip(name, route=_route(edges, start, end), depart=depart, actor=actor)


def build_scenario(scenario: Scenario, variant: Variant, script: Optional[Script]) -> Path:
    """Write a SMARTS scenario folder for one variant.

    With ``script=None`` the ego is an ordinary SUMO trip (reference driver); otherwise it
    is an agent mission starting at the same place and time.
    """
    mode = "sumo" if script is None else "agent"
    out = BUILD / "scenarios" / scenario.name / variant.name / mode
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copy(build_map(scenario.map), out / "map.net.xml")

    trips = [_trip(c.name, c.route, c.depart, c.start, c.speed) for c in variant.cars]
    missions = None
    if script is None:
        trips.append(_trip(EGO, scenario.ego_route, variant.ego_depart, variant.ego_start, end=EGO_END))
    else:
        missions = [t.Mission(
            route=_route(scenario.ego_route, variant.ego_start, EGO_END),
            entry_tactic=t.TrapEntryTactic(
                start_time=max(variant.ego_depart, 0.1),
                wait_to_hijack_limit_s=0,
                default_entry_speed=script.cruise,
            ),
        )]
    gen_scenario(
        t.Scenario(
            # duarouter rejects an empty trip list, so leave traffic out when there is none
            traffic={"staged": t.Traffic(engine="SUMO", flows=[], trips=trips)} if trips else None,
            ego_missions=missions,
        ),
        output_dir=out,
        seed=42,
    )
    return out

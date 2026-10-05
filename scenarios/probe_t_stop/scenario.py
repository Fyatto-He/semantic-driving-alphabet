"""Probe scenario: ego turns left from the stop-controlled minor leg of a T-junction.

Traffic is given as individual `Trip`s (not random flows) so that every run is
identical and decision branches can be staged on purpose.
"""
from pathlib import Path

from smarts.sstudio import gen_scenario
from smarts.sstudio import sstypes as t

car = t.TrafficActor(name="car", speed=t.Distribution(mean=1.0, sigma=0.0))

eastbound = t.Route(begin=("WJ", 0, 5), end=("JE", 0, "max"))
westbound = t.Route(begin=("EJ", 0, 5), end=("JW", 0, "max"))

traffic = t.Traffic(
    engine="SUMO",
    flows=[],
    trips=[
        t.Trip("east_1", route=eastbound, depart=0, actor=car),
        t.Trip("west_1", route=westbound, depart=2, actor=car),
        t.Trip("east_2", route=eastbound, depart=5, actor=car),
    ],
)

ego_mission = t.Mission(
    route=t.Route(begin=("SJ", 0, 20), end=("JW", 0, "max")),
    entry_tactic=t.TrapEntryTactic(start_time=0.1, wait_to_hijack_limit_s=0),
)

gen_scenario(
    scenario=t.Scenario(traffic={"basic": traffic}, ego_missions=[ego_mission]),
    output_dir=Path(__file__).parent,
)

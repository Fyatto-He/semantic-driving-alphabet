"""Scenario catalog.

A scenario is a map plus an ego route. Each *variant* stages one decision branch of that
scenario with a few individually timed background cars (no random traffic, so runs repeat
exactly). Every variant is driven by the SUMO reference driver, and by any ego scripts
listed for it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple

from semalpha.drivers import Hold, Script


@dataclass(frozen=True)
class Car:
    """One background vehicle driven by SUMO."""

    name: str
    route: Tuple[str, ...]   # edge ids, first to last
    depart: float            # seconds
    start: float = 5.0       # metres into the first edge
    speed: float = 1.0       # multiple of the speed limit it drives at


@dataclass(frozen=True)
class Variant:
    name: str
    story: str                                   # the decision branch, in words
    cars: Tuple[Car, ...] = ()
    ego_start: float = 20.0                      # metres into the first route edge
    ego_depart: float = 0.0                      # seconds
    scripts: Dict[str, Script] = field(default_factory=dict)   # extra scripted ego runs


@dataclass(frozen=True)
class Scenario:
    name: str
    map: str
    ego_route: Tuple[str, ...]
    summary: str
    variants: Tuple[Variant, ...]

    def variant(self, name: str) -> Variant:
        return next(v for v in self.variants if v.name == name)


# --------------------------------------------------------------------------------------
# A. T-junction: left turn out of the stop-controlled minor road
# --------------------------------------------------------------------------------------
_EAST = ("WJ", "JE")    # major road, left to right: crosses the ego's path
_WEST = ("EJ", "JW")    # major road, right to left: the ego merges into this stream

t_stop_left = Scenario(
    name="t_stop_left",
    map="t_stop",
    ego_route=("SJ", "JW"),
    summary="Left turn from the stop-controlled minor road onto the major road.",
    variants=(
        Variant(
            "clear",
            "No other traffic. A stop is still required before entering.",
            scripts={"roll_through": Script("Enters without stopping although nothing conflicts.")},
        ),
        Variant(
            "wait_for_gap",
            "Major-road traffic from both sides arrives as the ego reaches the line; "
            "the ego has to wait until both streams have passed.",
            cars=(Car("east_1", _EAST, depart=6), Car("west_1", _WEST, depart=8)),
            scripts={
                "enter_too_early": Script(
                    "Stops, then pulls out just in front of the car coming from the right.",
                    holds=(Hold("entry", until=13.5),)),
                "overcautious": Script(
                    "Stops and keeps waiting long after the road is clear.",
                    holds=(Hold("entry", until=26.0),)),
            },
        ),
        Variant(
            "gap_closes",
            "After the first car passes there is a short opening, but a second car closes it "
            "before the ego could finish the turn.",
            cars=(Car("east_1", _EAST, depart=4), Car("east_2", _EAST, depart=8),
                  Car("west_1", _WEST, depart=9)),
        ),
        Variant(
            "other_turns_off",
            "A major-road car approaches from the left but turns right into the ego's road. "
            "It never conflicts, yet that is only known once it starts turning.",
            cars=(Car("turner", ("WJ", "JS"), depart=5),),
            scripts={
                "wait_until_it_turns": Script(
                    "Waits at the line until the other car is visibly turning off, then goes.",
                    holds=(Hold("entry", until=13.0),)),
            },
        ),
    ),
)

# --------------------------------------------------------------------------------------
# B. T-junction: unprotected left turn from the major road
# --------------------------------------------------------------------------------------
t_major_left = Scenario(
    name="t_major_left",
    map="t_stop",
    ego_route=("EJ", "JS"),
    summary="Left turn from the major road into the minor road, across oncoming traffic.",
    variants=(
        Variant(
            "clear",
            "No oncoming traffic. No stop is required; the ego turns without waiting.",
        ),
        Variant(
            "oncoming_then_gap",
            "Two oncoming cars go straight through; the ego waits for both, then turns.",
            cars=(Car("oncoming_1", _EAST, depart=1), Car("oncoming_2", _EAST, depart=3)),
            scripts={
                "turn_across": Script(
                    "Turns straight across the path of the first oncoming car.", cruise=13.0),
                "wait_in_junction": Script(
                    "Pulls forward to the in-junction waiting point and waits there until both have passed.",
                    cruise=13.0, holds=(Hold("waiting_point", until=10.5),)),
            },
        ),
        Variant(
            "minor_car_waiting",
            "A car waits at the stop sign on the minor road. The ego has priority over it "
            "and nothing is oncoming.",
            cars=(Car("minor_1", ("SJ", "JW"), depart=0, start=60),),
        ),
        Variant(
            "oncoming_turns_right",
            "The oncoming car turns right into the same road the ego is turning into: "
            "the paths merge instead of crossing.",
            cars=(Car("oncoming_1", ("WJ", "JS"), depart=2),),
        ),
    ),
)

# --------------------------------------------------------------------------------------
# C. Signalized four-way junction
# --------------------------------------------------------------------------------------
_CROSS_E = ("WJ", "JE")
_CROSS_W = ("EJ", "JW")

signal_straight = Scenario(
    name="signal_straight",
    map="cross_signal",
    ego_route=("SJ", "JN"),
    summary="Straight through a signalized four-way junction.",
    variants=(
        Variant(
            "green",
            "The signal is green on arrival and stays green.",
            ego_depart=0.0,
        ),
        Variant(
            "red_then_green",
            "The signal is red on arrival; cross traffic passes; then it turns green.",
            ego_depart=36.0,
            cars=(Car("cross_1", _CROSS_E, depart=36), Car("cross_2", _CROSS_W, depart=37)),
            scripts={"run_red": Script("Drives through the red signal into cross traffic.", cruise=13.0)},
        ),
        Variant(
            "yellow_far",
            "Green turns yellow while the ego is still far from the line: there is room to stop.",
            ego_depart=18.0,
        ),
        Variant(
            "yellow_near",
            "Green turns yellow when the ego is almost at the line: stopping would need hard braking.",
            ego_depart=15.7,
        ),
    ),
)

signal_left = Scenario(
    name="signal_left",
    map="cross_signal",
    ego_route=("SJ", "JW"),
    summary="Left turn on a permissive green at a signalized four-way junction.",
    variants=(
        Variant(
            "oncoming_then_gap",
            "Green, but oncoming traffic is going straight: the ego waits inside the junction, then turns.",
            cars=(Car("oncoming_1", ("NJ", "JS"), depart=0, start=10),
                  Car("oncoming_2", ("NJ", "JS"), depart=2, start=10)),
        ),
    ),
)

# --------------------------------------------------------------------------------------
# D. Roundabout: enter from the south arm, leave by the north arm (second exit)
# --------------------------------------------------------------------------------------
roundabout = Scenario(
    name="roundabout",
    map="roundabout",
    ego_route=("S_in", "ring_SE", "ring_EN", "N_out"),
    summary="Enter a single-lane roundabout, pass one exit, leave at the second.",
    variants=(
        Variant(
            "empty",
            "Nobody on the ring. The ego may enter without stopping.",
        ),
        Variant(
            "yield_to_circulating",
            "A car already on the ring passes the ego's entry; the ego gives way, then enters.",
            cars=(Car("ring_1", ("W_in", "ring_WS", "ring_SE", "E_out"), depart=0, start=30),),
            scripts={
                "cut_in": Script(
                    "Stops at the yield line, then enters directly in front of the circulating car.",
                    cruise=13.0, holds=(Hold("entry", until=8.0),)),
            },
        ),
        Variant(
            "circulating_exits",
            "A car on the ring approaches the ego's entry but leaves by the ego's own arm, "
            "so it never passes in front of the ego.",
            cars=(Car("ring_1", ("W_in", "ring_WS", "S_out"), depart=0, start=30),),
            scripts={
                "wait_until_it_exits": Script(
                    "Waits at the yield line until the other car has visibly left the ring, then enters.",
                    cruise=13.0, holds=(Hold("entry", until=9.5),)),
            },
        ),
        Variant(
            "entering_car_yields",
            "While the ego is on the ring, a car arrives at the next entry and has to give way to the ego.",
            cars=(Car("east_arm", ("E_in", "ring_EN", "ring_NW", "W_out"), depart=2),),
        ),
    ),
)

SCENARIOS = {s.name: s for s in (t_stop_left, t_major_left, signal_straight, signal_left, roundabout)}

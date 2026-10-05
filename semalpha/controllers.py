"""Controller automata: a DFA over the labels that drives the ego.

A rule automaton (rules.py) watches a run and judges it. A controller automaton reads the
same labels but is in charge: each of its states carries an *action*, and the action of
the state it is in is what the ego does. Nothing else decides. The question this answers
is whether the label alphabet is enough to drive on, not only to judge with.

There are four actions:

    go            follow the route at cruising speed
    hold_at_line  come to a halt at the junction's entry line (on the spot, if already over it)
    hold_inside   already inside the junction: halt short of any road shared with others
    stop          brake to a halt right here

Turning an action into a target speed is done by :class:`Executor`. It knows the geometry
of the ego's own route (where the line is, where shared road begins, how tight the turn
is) and nothing about other traffic: every decision that depends on traffic, signs or
signals is taken by the automaton, from the labels.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from semalpha.automata import Automaton
from semalpha.mapinfo import MapInfo, RoutePath

GO, HOLD_AT_LINE, HOLD_INSIDE, STOP = "go", "hold_at_line", "hold_inside", "stop"


@dataclass(frozen=True)
class Controller:
    name: str
    idea: str                    # the driving policy in plain words
    automaton: Automaton
    actions: Dict[str, str]      # state -> action

    def __post_init__(self):
        missing = [s for s in self.automaton.states if s not in self.actions]
        if missing:
            raise ValueError(f"controller {self.name}: no action for state(s) {missing}")


class Executor:
    """Turns the controller's action into a target speed for SMARTS' lane-following ego."""

    CRUISE = 0.9          # fraction of the speed limit to cruise at
    TURN = 0.8            # fraction of an in-junction lane's speed limit to turn at
    DECEL = 3.0           # m/s^2 used to plan stops and slow-downs
    MARGIN = 1.0          # m between the front bumper and the point held at

    def __init__(self, mapinfo: MapInfo, path: RoutePath):
        self.mapinfo, self.path = mapinfo, path
        self._turns = [(path.starts[i], self.TURN * mapinfo.speed_limit(lane))
                       for i, lane in enumerate(path.lanes) if mapinfo.is_internal(lane)]

    def entry_speed(self) -> float:
        return self.CRUISE * self.mapinfo.speed_limit(self.path.lanes[0])

    def speed(self, view, action: str) -> float:
        lane = self.path.lane_at(view.s)
        limit = self.mapinfo.speed_limit(lane)
        speed = (self.TURN if self.mapinfo.is_internal(lane) else self.CRUISE) * limit
        for start, turn_speed in self._turns:          # slow down in time for the turns ahead
            if start > view.front:
                speed = min(speed, (turn_speed ** 2 + 2 * self.DECEL * (start - view.front)) ** 0.5)
        if action == GO:
            return float(speed)
        if action == STOP:
            return 0.0
        if action == HOLD_AT_LINE:
            if view.region is None or view.inside:     # already over the line: halt on the spot,
                return 0.0                             # do not roll on to the edge of shared road
            room = view.dist_to_entry
        else:
            room = view.dist_to_shared
        room = (room if room is not None else 0.0) - self.MARGIN
        if room < 0.3:
            return 0.0
        return float(min(speed, (2 * self.DECEL * room) ** 0.5))


# ---- the first controller ------------------------------------------------------------------
# Reasons not to move forward. Conditions are ANDs of labels, so "any of these" is one
# transition per reason.
_UNSAFE_GAP = "conflict_present !ego_has_priority !gap_safe"       # someone who outranks me is too close
_NOT_YIELDING = "conflict_present !gap_safe !others_can_yield"     # someone who owes me priority cannot stop any more
_HOLD_REASONS = (
    "signal_stop",
    "signal_caution",
    _UNSAFE_GAP,
    _NOT_YIELDING,
    "path_blocked",
    "!exit_clear",
)

junction_v1 = Controller(
    name="dfa_v1",
    idea="Stop where a stop sign says so. Hold at the line for a red or stoppable yellow signal, "
         "for a car that outranks me and is too close, or for a blocked path or exit. "
         "Otherwise go. Once past the point of no return, keep going.",
    automaton=Automaton(
        name="dfa_v1",
        kind="controller",
        rule="Drives the ego: the action of the current state is what the car does.",
        initial="drive",
        transitions={
            "drive": (
                ("in_junction !in_waiting_area", "cross"),
                ("in_junction", "enter"),
                ("stop_sign", "stop_first"),
                ("signal_stop", "wait_at_line"),
                ("signal_caution can_stop_before_entry", "wait_at_line"),
                (_UNSAFE_GAP, "wait_at_line"),
                (_NOT_YIELDING, "wait_at_line"),
                ("path_blocked", "wait_at_line"),
                ("!exit_clear approaching_junction", "wait_at_line"),
                ("!exit_clear at_entry_line", "wait_at_line"),
            ),
            # a stop sign: a full halt at the line comes before any judgement of the traffic
            "stop_first": (
                ("at_entry_line ego_stopped", "wait_at_line"),
                ("in_junction", "enter"),
            ),
            "wait_at_line": (
                ("in_junction !in_waiting_area", "cross"),
                *((reason, "wait_at_line") for reason in _HOLD_REASONS),
                ("", "enter"),                          # no reason left to hold
            ),
            # moving off: still able to hold, at the line or just inside
            "enter": (
                ("in_junction !in_waiting_area", "cross"),
                ("signal_stop !in_junction", "wait_at_line"),
                ("signal_caution can_stop_before_entry !in_junction", "wait_at_line"),
                (_UNSAFE_GAP + " in_junction", "wait_inside"),
                (_NOT_YIELDING + " in_junction", "wait_inside"),
                ("path_blocked in_junction", "wait_inside"),
                (_UNSAFE_GAP, "wait_at_line"),
                (_NOT_YIELDING, "wait_at_line"),
                ("path_blocked", "wait_at_line"),
                ("!exit_clear !in_junction", "wait_at_line"),
                ("!in_junction !at_entry_line !approaching_junction", "drive"),
            ),
            "wait_inside": (
                ("in_junction !in_waiting_area", "cross"),
                (_UNSAFE_GAP, "wait_inside"),
                (_NOT_YIELDING, "wait_inside"),
                ("path_blocked", "wait_inside"),
                ("", "enter"),
            ),
            # committed: finish crossing whatever happens
            "cross": (
                ("!in_junction", "drive"),
            ),
        },
    ),
    actions={
        "drive": GO,
        "stop_first": HOLD_AT_LINE,
        "wait_at_line": HOLD_AT_LINE,
        "enter": GO,
        "wait_inside": HOLD_INSIDE,
        "cross": GO,
    },
)

# ---- the second controller: a design that did not work ---------------------------------------
# In random traffic dfa_v1 sometimes flipped between going and holding from one frame to the
# next. This was the first attempt at a cure, with two changes that states can express:
#   * leave the line only after three frames in a row without a reason to hold;
#   * decide at the line, and once moving do not stop again inside the junction.
# It did worse, with two collisions: a car with right of way that is standing still reads as
# a safe gap, so the ego commits, and then both move off together. It is kept as the example
# of a controller the tests reject. See docs/design_log.md.
def _hold_or(next_state: str):
    return (*((reason, "wait_at_line") for reason in _HOLD_REASONS), ("", next_state))


junction_v2 = Controller(
    name="dfa_v2",
    idea="As dfa_v1, but steadier: it leaves the line only after three frames in a row without a "
         "reason to hold, it makes that decision at the line, and once it has moved off it does "
         "not stop again inside the junction.",
    automaton=Automaton(
        name="dfa_v2",
        kind="controller",
        rule="Drives the ego: the action of the current state is what the car does.",
        initial="drive",
        transitions={
            "drive": (
                ("in_junction", "cross"),
                ("stop_sign", "stop_first"),
                ("signal_stop", "wait_at_line"),
                ("signal_caution can_stop_before_entry", "wait_at_line"),
                (_UNSAFE_GAP, "wait_at_line"),
                (_NOT_YIELDING, "wait_at_line"),
                ("path_blocked", "wait_at_line"),
                ("!exit_clear approaching_junction", "wait_at_line"),
                ("!exit_clear at_entry_line", "wait_at_line"),
                ("at_entry_line", "go"),                 # at the line with nothing against it: committed
            ),
            "stop_first": (
                ("at_entry_line ego_stopped", "wait_at_line"),
                ("in_junction", "cross"),
            ),
            "wait_at_line": (("in_junction !in_waiting_area", "cross"), *_hold_or("clear_1")),
            "clear_1": (("in_junction !in_waiting_area", "cross"), *_hold_or("clear_2")),
            "clear_2": (
                ("in_junction !in_waiting_area", "cross"),
                *((reason, "wait_at_line") for reason in _HOLD_REASONS),
                ("at_entry_line", "go"),                 # three clear frames, and at the line: committed
                ("in_junction", "go"),
                ("", "drive"),                           # clear, but still some way off: keep judging while rolling up
            ),
            "go": (
                ("in_junction", "cross"),
                ("!at_entry_line !approaching_junction", "drive"),
            ),
            "cross": (
                ("!in_junction", "drive"),
            ),
        },
    ),
    actions={
        "drive": GO,
        "stop_first": HOLD_AT_LINE,
        "wait_at_line": HOLD_AT_LINE,
        "clear_1": HOLD_AT_LINE,
        "clear_2": HOLD_AT_LINE,
        "go": GO,
        "cross": GO,
    },
)

# ---- the third controller --------------------------------------------------------------------
# The cause of dfa_v1's flipping was in the labels, not in the automaton: "someone who
# outranks me is too close" was spelled `!ego_has_priority !gap_safe`, which is also true when
# one car outranks the ego from far away and another car, which owes the ego priority, is
# close. dfa_v3 is dfa_v1 with two changes:
#   * that reason is spelled with the label `priority_gap_safe`, which was added for this and
#     keeps both facts about the same car;
#   * `cross` is no longer blind. With the needless waits gone, the ego met a car that should
#     have given way on the roundabout and did not, and was hit. The new state `avoid` brakes
#     for as long as a car that owes the ego priority can no longer stop short of its path.
_OUTRANKED = "!priority_gap_safe"


def _rebound(transitions: Dict[str, tuple]) -> Dict[str, tuple]:
    return {state: tuple((condition.replace(_UNSAFE_GAP, _OUTRANKED), target) for condition, target in moves)
            for state, moves in transitions.items()}


junction_v3 = Controller(
    name="dfa_v3",
    idea="As dfa_v1, with two changes. 'A car that outranks me is too close' is read from the "
         "label priority_gap_safe, so that both halves of it are about the same car. "
         "And while crossing, it brakes if a car that should give way can no longer stop.",
    automaton=Automaton(
        name="dfa_v3",
        kind="controller",
        rule="Drives the ego: the action of the current state is what the car does.",
        initial="drive",
        transitions={
            **_rebound(junction_v1.automaton.transitions),
            "cross": (
                ("!in_junction", "drive"),
                (_NOT_YIELDING, "avoid"),
            ),
            "avoid": (
                ("!in_junction", "drive"),
                (_NOT_YIELDING, "avoid"),
                ("", "cross"),
            ),
        },
    ),
    actions={**junction_v1.actions, "avoid": STOP},
)

CONTROLLERS: Dict[str, Controller] = {c.name: c for c in (junction_v1, junction_v2, junction_v3)}

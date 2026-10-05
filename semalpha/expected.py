"""Expected label sequences, written from the human traces in docs/traces.md.

These were written BEFORE the labeling functions, so comparing them with the labels
actually produced is a test of the vocabulary rather than a description of it.

An expectation is an ordered list of *phases*. A phase names the driver's situation and
lists the propositions that must be true (``name``) or false (``!name``) during it;
anything not listed is free. A run matches when its frames pass through the phases in
order. ``never`` lists combinations that must not occur in any frame.

Revisions after the first comparison (see docs/design_log.md):
- optional in-between phases (`opt`) were added for the moments between two milestones,
  such as moving off the line;
- roundabout/cut_in was restaged and now ends in a crash, so its last milestone is `collision`;
- t_stop_left/overcautious: "the road is free" no longer requires `!conflict_present`,
  because `gap_safe` turns true 0.4 s before the last car counts as having passed.
No other milestone and no forbidden combination was changed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

Phase = Tuple   # (situation in words, literals) or, for an optional phase, (situation, literals, True)


def opt(name: str, literals: str) -> Phase:
    """An in-between phase that a run may pass through or skip."""
    return (name, literals, True)


@dataclass(frozen=True)
class Expectation:
    phases: Tuple[Phase, ...]
    never: Tuple[str, ...] = ()


# ---- building blocks -----------------------------------------------------------------
UP = ("driving up to the junction", "!in_junction !ego_stopped")
CROSS = ("crossing the junction", "in_junction")
OUT = ("out of the junction", "!in_junction !at_entry_line")
DONE = ("destination reached", "goal_reached")
MOVING_OFF = opt("moving off the line", "at_entry_line !ego_stopped")
NOSING_IN = opt("inside, still short of anyone else's path", "in_junction in_waiting_area")
REST = opt("crossing the rest of the junction", "in_junction")

# Past the point of no return while a car that outranks the ego is too close.
UNSAFE = "in_junction !in_waiting_area conflict_present !ego_has_priority !gap_safe"
SAFE = ("collision", "off_road", UNSAFE)

HELD_AT_LINE = "at_entry_line ego_stopped conflict_present !ego_has_priority !gap_safe"
FREE_AT_LINE = ("at the line, free to go", "at_entry_line gap_safe")
IN_WAITING_AREA = "in_waiting_area conflict_present !ego_has_priority !gap_safe"

EXPECTED: Dict[Tuple[str, str, str], Expectation] = {
    # ---- A. left turn out of the stop-controlled side road ------------------------------
    ("t_stop_left", "clear", "sumo"): Expectation(
        (UP,
         ("stopped at the stop line, road empty", "at_entry_line ego_stopped stop_sign !conflict_present gap_safe"),
         FREE_AT_LINE, ("crossing, nobody around", "in_junction !conflict_present"), OUT, DONE),
        never=SAFE),
    ("t_stop_left", "clear", "roll_through"): Expectation(
        (UP, ("at the stop line, still moving", "at_entry_line stop_sign !ego_stopped"), CROSS, OUT, DONE),
        never=("at_entry_line ego_stopped", "collision")),
    ("t_stop_left", "wait_for_gap", "sumo"): Expectation(
        (UP, ("held at the stop line by traffic that outranks me", HELD_AT_LINE + " stop_sign"),
         FREE_AT_LINE, CROSS, OUT, DONE),
        never=SAFE),
    ("t_stop_left", "wait_for_gap", "enter_too_early"): Expectation(
        (UP, ("held at the stop line", HELD_AT_LINE), MOVING_OFF, NOSING_IN,
         ("pulled out in front of a car that outranks me", UNSAFE), REST, OUT, DONE)),
    ("t_stop_left", "wait_for_gap", "overcautious"): Expectation(
        (UP, ("held at the stop line", HELD_AT_LINE),
         ("still stopped although the gap is sufficient", "at_entry_line ego_stopped gap_safe"),
         MOVING_OFF, CROSS, OUT, DONE),
        never=SAFE),
    ("t_stop_left", "gap_closes", "sumo"): Expectation(
        (UP, ("held at the stop line; the short opening is not enough", HELD_AT_LINE),
         FREE_AT_LINE, CROSS, OUT, DONE),
        never=SAFE),
    ("t_stop_left", "other_turns_off", "sumo"): Expectation(
        (UP, ("at the stop line; the other car might cross my path", HELD_AT_LINE), MOVING_OFF, NOSING_IN,
         ("entered anyway (the simulator's driver knows the other car's route)", UNSAFE),
         ("the other car is visibly turning off", "in_junction !conflict_present"), OUT, DONE),
        never=("collision",)),
    ("t_stop_left", "other_turns_off", "wait_until_it_turns"): Expectation(
        (UP, ("at the stop line; the other car might cross my path", HELD_AT_LINE),
         ("the other car is visibly turning off", "at_entry_line !conflict_present gap_safe"),
         CROSS, OUT, DONE),
        never=SAFE),

    # ---- B. unprotected left turn from the main road -------------------------------------
    ("t_major_left", "clear", "sumo"): Expectation(
        (UP, ("crossing, nobody around", "in_junction !conflict_present !ego_stopped"), OUT, DONE),
        never=SAFE + ("ego_stopped", "stop_sign")),
    ("t_major_left", "oncoming_then_gap", "sumo"): Expectation(
        (UP, ("pulling into the waiting area", IN_WAITING_AREA),
         ("held in the waiting area by oncoming traffic", IN_WAITING_AREA + " ego_stopped"),
         ("gap opens", "in_junction gap_safe"), OUT, DONE),
        never=SAFE + ("stop_sign",)),
    ("t_major_left", "oncoming_then_gap", "wait_in_junction"): Expectation(
        (UP, ("pulling into the waiting area", IN_WAITING_AREA),
         ("held in the waiting area by oncoming traffic", IN_WAITING_AREA + " ego_stopped"),
         ("gap opens", "in_junction gap_safe"), OUT, DONE),
        never=SAFE),
    ("t_major_left", "oncoming_then_gap", "turn_across"): Expectation(
        (UP, NOSING_IN, ("turning across a car that outranks me", UNSAFE), ("crash", "collision"))),
    ("t_major_left", "minor_car_waiting", "sumo"): Expectation(
        (UP,
         ("a side-road car owes me priority and can still stop",
          "!in_junction conflict_present ego_has_priority others_can_yield"),
         ("crossing with priority", "in_junction ego_has_priority"), OUT, DONE),
        never=("collision", "off_road", "ego_stopped", "conflict_present !ego_has_priority")),
    ("t_major_left", "oncoming_turns_right", "sumo"): Expectation(
        (UP, ("pulling into the waiting area", IN_WAITING_AREA),
         ("held in the waiting area; its path merges with mine", IN_WAITING_AREA + " ego_stopped"),
         ("gap opens", "in_junction gap_safe"), OUT, DONE),
        never=SAFE),

    # ---- C. signalized four-way ---------------------------------------------------------
    ("signal_straight", "green", "sumo"): Expectation(
        (UP, ("approaching on green", "signal_go !in_junction !ego_stopped"),
         ("crossing on green", "in_junction signal_go"), OUT, DONE),
        never=SAFE + ("ego_stopped", "signal_stop", "signal_caution")),
    ("signal_straight", "red_then_green", "sumo"): Expectation(
        (UP, ("approaching on red, room to stop", "signal_stop !in_junction can_stop_before_entry"),
         ("stopped at the line on red", "at_entry_line ego_stopped signal_stop"),
         ("green, still at the line", "at_entry_line signal_go"),
         ("crossing on green", "in_junction signal_go"), OUT, DONE),
        never=SAFE + ("in_junction signal_stop",)),
    ("signal_straight", "red_then_green", "run_red"): Expectation(
        (UP, ("approaching on red", "signal_stop !in_junction"),
         ("inside on red while cross traffic outranks me", "in_junction signal_stop conflict_present !ego_has_priority"),
         OUT, DONE)),
    ("signal_straight", "yellow_far", "sumo"): Expectation(
        (UP, ("approaching on green", "signal_go !in_junction"),
         ("yellow, room to stop", "signal_caution !in_junction can_stop_before_entry"),
         opt("red, still rolling up to the line", "signal_stop !in_junction !ego_stopped"),
         ("stopped at the line on red", "at_entry_line ego_stopped signal_stop"),
         ("green, still at the line", "at_entry_line signal_go"),
         ("crossing on green", "in_junction signal_go"), OUT, DONE),
        never=SAFE + ("in_junction signal_stop", "in_junction signal_caution")),
    ("signal_straight", "yellow_near", "sumo"): Expectation(
        (UP, ("approaching on green", "signal_go !in_junction"),
         ("yellow, no room to stop", "signal_caution !in_junction !can_stop_before_entry"),
         ("crossing on yellow", "in_junction signal_caution"), OUT, DONE),
        never=SAFE + ("ego_stopped", "signal_caution can_stop_before_entry")),
    ("signal_left", "oncoming_then_gap", "sumo"): Expectation(
        (UP, ("green; pulling into the waiting area", IN_WAITING_AREA + " signal_go"),
         ("held in the waiting area by oncoming traffic", IN_WAITING_AREA + " ego_stopped signal_go"),
         ("gap opens", "in_junction gap_safe"), OUT, DONE),
        never=SAFE),

    # ---- D. roundabout ------------------------------------------------------------------
    ("roundabout", "empty", "sumo"): Expectation(
        (UP, ("on the ring, nobody around", "in_junction !conflict_present"), OUT, DONE),
        never=SAFE + ("ego_stopped", "stop_sign", "conflict_present")),
    ("roundabout", "yield_to_circulating", "sumo"): Expectation(
        (UP, ("held at the yield line by a car on the ring", HELD_AT_LINE + " !stop_sign"),
         FREE_AT_LINE, CROSS, OUT, DONE),
        never=SAFE),
    ("roundabout", "yield_to_circulating", "cut_in"): Expectation(
        (UP, ("a ring car that outranks me is too close", "!in_junction conflict_present !ego_has_priority !gap_safe"),
         NOSING_IN, ("entered in front of it", UNSAFE), ("crash", "collision"))),
    ("roundabout", "circulating_exits", "sumo"): Expectation(
        (UP, ("a ring car might pass in front of me", "!in_junction conflict_present !ego_has_priority !gap_safe"),
         NOSING_IN, ("entered anyway (the simulator's driver knows the other car's route)", UNSAFE),
         ("the other car has visibly left the ring", "in_junction !conflict_present"), OUT, DONE),
        never=("collision",)),
    ("roundabout", "circulating_exits", "wait_until_it_exits"): Expectation(
        (UP, ("a ring car might pass in front of me", "!in_junction conflict_present !ego_has_priority !gap_safe"),
         ("the other car has visibly left the ring", "at_entry_line !conflict_present gap_safe"),
         CROSS, OUT, DONE),
        never=SAFE),
    ("roundabout", "entering_car_yields", "sumo"): Expectation(
        (UP, ("on the ring", "in_junction"),
         ("a car at the next entry owes me priority and can still stop",
          "in_junction conflict_present ego_has_priority others_can_yield"),
         REST, OUT, DONE),
        never=("collision", "off_road", "ego_stopped", "conflict_present !ego_has_priority")),
}

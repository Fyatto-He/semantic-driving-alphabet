"""The rule set for crossing a junction: one set of small automata for every scenario.

Nothing here mentions a junction type. Each automaton is written against the labels only,
so the same set judges a stop-sign junction, a signalized one and a roundabout. Whether it
judges them correctly is the test of the label alphabet.

Three kinds:
  task    reach_goal            how far the ego has got; `done` means success
  rule    (six of them)         each watches one rule; `violated` is never left
  branch  where_it_waited       which way the ego got through, for telling runs apart
"""
from __future__ import annotations

from typing import Dict, List

from semalpha.automata import Automaton

# The ego is past the point of no return: inside the junction and beyond the waiting area.
COMMITTED = "in_junction !in_waiting_area"

reach_goal = Automaton(
    name="reach_goal",
    kind="task",
    rule="Drive up to the junction, cross it, and reach the destination.",
    initial="approach",
    transitions={
        "approach": (("goal_reached", "done"), ("in_junction", "inside"), ("at_entry_line", "at_line")),
        "at_line": (("in_junction", "inside"),),
        "inside": (("goal_reached", "done"), ("!in_junction", "cleared")),
        "cleared": (("goal_reached", "done"), ("in_junction", "inside"), ("at_entry_line", "at_line")),
    },
    good=("done",),
)

no_collision = Automaton(
    name="no_collision",
    rule="Never touch another car.",
    initial="ok",
    transitions={"ok": (("collision", "violated"),)},
    bad=("violated",),
)

stay_on_road = Automaton(
    name="stay_on_road",
    rule="Never leave the road.",
    initial="ok",
    transitions={"ok": (("off_road", "violated"),)},
    bad=("violated",),
)

stop_at_stop_sign = Automaton(
    name="stop_at_stop_sign",
    rule="Where a stop sign applies, come to a halt at the line before entering.",
    initial="idle",
    transitions={
        "idle": (("stop_sign at_entry_line ego_stopped", "stopped"),
                 ("stop_sign in_junction", "violated"),
                 ("stop_sign", "stop_owed")),
        "stop_owed": (("at_entry_line ego_stopped", "stopped"),
                      ("in_junction", "violated")),
        "stopped": (("!stop_sign !in_junction", "idle"),),     # junction left behind: ready for the next one
    },
    bad=("violated",),
)

obey_red_signal = Automaton(
    name="obey_red_signal",
    rule="Do not enter the junction while the signal is red. "
         "Being inside when it turns red is not a violation.",
    initial="outside",
    transitions={
        "outside": (("in_junction signal_stop", "violated"),
                    ("in_junction", "inside")),
        "inside": (("!in_junction", "outside"),),
    },
    bad=("violated",),
)

stop_on_yellow_when_able = Automaton(
    name="stop_on_yellow_when_able",
    rule="If the signal is yellow while there is still room to stop, do not enter on that yellow.",
    initial="free",
    transitions={
        "free": (("signal_caution can_stop_before_entry !in_junction", "stop_owed"),),
        "stop_owed": (("in_junction signal_caution", "violated"),
                      ("signal_go", "free"),
                      ("in_junction", "free")),        # entered on red: that is the red rule's business
    },
    bad=("violated",),
)

respect_right_of_way = Automaton(
    name="respect_right_of_way",
    rule="Do not go past the point of no return while a car that outranks the ego is too close. "
         "Judged at the moment of committing; what happens afterwards is not held against the ego.",
    initial="uncommitted",
    transitions={
        # one label for "a car that outranks the ego is too close": with `!ego_has_priority
        # !gap_safe` the two halves could be about two different cars
        "uncommitted": ((COMMITTED + " !priority_gap_safe", "violated"),
                        (COMMITTED, "committed")),
        "committed": (("!in_junction", "uncommitted"),),
    },
    bad=("violated",),
)

where_it_waited = Automaton(
    name="where_it_waited",
    kind="branch",
    rule="Records where the ego came to a halt on its way through: at the entry line, "
         "inside the junction short of anyone's path, both, or nowhere.",
    initial="nowhere",
    transitions={
        "nowhere": (("at_entry_line ego_stopped", "at_line"),
                    ("in_junction in_waiting_area ego_stopped", "inside")),
        "at_line": (("in_junction in_waiting_area ego_stopped", "both"),),
        "inside": (("at_entry_line ego_stopped", "both"),),
    },
)

AUTOMATA: List[Automaton] = [
    reach_goal,
    stop_at_stop_sign,
    obey_red_signal,
    stop_on_yellow_when_able,
    respect_right_of_way,
    no_collision,
    stay_on_road,
    where_it_waited,
]
BY_NAME: Dict[str, Automaton] = {a.name: a for a in AUTOMATA}
RULES = [a for a in AUTOMATA if a.kind == "rule"]

# Not an automaton, because it needs to count time: how long the ego stood still although
# nothing held it (gap sufficient, no red or yellow signal).
IDLE_WHILE_FREE = ("at_entry_line ego_stopped gap_safe !signal_stop !signal_caution",
                   "in_junction in_waiting_area ego_stopped gap_safe")

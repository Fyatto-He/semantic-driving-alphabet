"""Layer 3: the propositions exposed to the automaton.

Each proposition is a function of one frame's :class:`~semalpha.relations.View` and
returns True or False. It states a fact about the world, never what the ego should do.
Add or remove a proposition by adding or removing a function here; the order of
definition is the order used in every trace and figure.
"""
from __future__ import annotations

from typing import Callable, Dict

from semalpha.relations import View

PROPOSITIONS: Dict[str, Callable[[View], bool]] = {}
GROUP: Dict[str, str] = {}


def proposition(group: str):
    def register(fn):
        PROPOSITIONS[fn.__name__] = fn
        GROUP[fn.__name__] = group
        return fn
    return register


# ---- junction progress: where the ego is relative to the junction on its route -----------

@proposition("progress")
def approaching_junction(v: View) -> bool:
    """The junction's entry line is ahead, within the approach horizon, and not yet reached."""
    return v.approaching


@proposition("progress")
def at_entry_line(v: View) -> bool:
    """The ego's front bumper is at the stop / yield / signal line."""
    return v.at_entry


@proposition("progress")
def in_junction(v: View) -> bool:
    """The ego's front is past the entry line and its rear has not left the junction."""
    return v.inside


@proposition("progress")
def in_waiting_area(v: View) -> bool:
    """The ego is inside the junction but has not reached any road it shares with another movement."""
    return v.before_shared_area


# ---- control: what the ego's approach obliges regardless of traffic ----------------------

@proposition("control")
def stop_sign(v: View) -> bool:
    """The ego's movement through this junction is stop-controlled."""
    return v.entry_control in ("stop", "allway_stop")


@proposition("control")
def signal_go(v: View) -> bool:
    return v.entry_signal == "GO"


@proposition("control")
def signal_caution(v: View) -> bool:
    return v.entry_signal == "CAUTION"


@proposition("control")
def signal_stop(v: View) -> bool:
    return v.entry_signal == "STOP"


# ---- interaction: quantified over every car whose possible path meets the ego's ----------

@proposition("interaction")
def conflict_present(v: View) -> bool:
    """Some car's possible path meets the ego's remaining path, and neither has passed that place."""
    return bool(v.conflicts)


@proposition("interaction")
def ego_has_priority(v: View) -> bool:
    """The rules give the ego right of way over every such car (true when there is none)."""
    return all(v.has_priority(c) for c in v.conflicts)


@proposition("interaction")
def gap_safe(v: View) -> bool:
    """Going now, the ego would be clear of every such car by the time margin (true when there is none)."""
    return all(v.gap_safe(c) for c in v.conflicts)


@proposition("interaction")
def others_can_yield(v: View) -> bool:
    """Every car that owes the ego priority, whichever way it may be going, can still stop
    short of the ego's path (true when there is none)."""
    by_car = {}
    for c in v.conflicts:
        by_car.setdefault(c.other, []).append(c)
    return all(v.can_yield(c)
               for conflicts in by_car.values() if all(v.has_priority(c) for c in conflicts)
               for c in conflicts)


# ---- occupancy ---------------------------------------------------------------------------

@proposition("occupancy")
def path_blocked(v: View) -> bool:
    """A car is physically on the ego's path inside the junction."""
    return v.path_blocked


@proposition("occupancy")
def exit_clear(v: View) -> bool:
    """Beyond the junction there is room for the ego to leave it completely."""
    return v.exit_clear


# ---- ego motion --------------------------------------------------------------------------

@proposition("ego motion")
def ego_stopped(v: View) -> bool:
    return v.ego.speed < v.th.stopped_speed


@proposition("ego motion")
def can_stop_before_entry(v: View) -> bool:
    """At a comfortable deceleration the ego can still halt before the entry line."""
    return v.can_stop_before_entry


# ---- terminal ----------------------------------------------------------------------------

@proposition("terminal")
def collision(v: View) -> bool:
    return v.event("collision") or v.touching


@proposition("terminal")
def off_road(v: View) -> bool:
    return v.event("off_road") or not v.on_road


@proposition("terminal")
def goal_reached(v: View) -> bool:
    return v.event("reached_goal") or v.s >= v.scene.goal_s - v.th.goal_tolerance_m

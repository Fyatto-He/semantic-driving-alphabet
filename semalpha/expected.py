"""What each run is expected to show, stored in expectations.json.

Two things are expected of every run, keyed by "scenario/variant/driver":

* a **label sequence**: an ordered list of phases. A phase names the driver's situation
  and lists the labels that must be on (``name``) or off (``!name``) during it; labels not
  listed are free. A phase may be optional, and may carry the time at which it is expected
  to begin. ``never`` lists combinations that must not occur in any frame. label.py checks
  the labels against this.
* a **verdict**: whether the ego reaches its destination, which rules it breaks, and
  where it comes to a halt. verify.py checks the rule automata against this.

Edit expectations in the inspector (``python -m semalpha.serve``), not here: the page
checks every change against the recorded run as you make it and saves to
expectations.json. The file is plain JSON and can also be edited by hand.

The first version of every expectation was written before the code it tests (the label
sequences before the labeling functions, the verdicts before the automata). The history
is in docs/design_log.md.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

FILE = Path(__file__).with_name("expectations.json")
Key = Tuple[str, str, str]            # (scenario, variant, driver)


@dataclass(frozen=True)
class Phase:
    name: str                         # the situation, in words
    labels: str                       # labels that must be on ("name") or off ("!name")
    optional: bool = False            # a run may skip this phase
    at: Optional[float] = None        # second at which the phase is expected to begin, if one was given


@dataclass(frozen=True)
class Expectation:
    phases: Tuple[Phase, ...] = ()
    never: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Verdict:
    completed: bool = True
    violations: Tuple[str, ...] = ()
    waited: str = "nowhere"


class _Table(dict):
    """A dict that answers with an empty expectation for a run nobody has described yet."""

    def __init__(self, empty):
        super().__init__()
        self._empty = empty

    def __missing__(self, key):
        return self._empty


EXPECTED: Dict[Key, Expectation] = _Table(Expectation())
EXPECTED_VERDICT: Dict[Key, Verdict] = _Table(Verdict())


def check(data: dict) -> None:
    """Raise ValueError unless `data` has the shape of expectations.json."""
    from semalpha.predicates import PROPOSITIONS
    from semalpha.rules import RULES, where_it_waited

    rules = {r.name for r in RULES}

    def literals(text, where):
        if not isinstance(text, str):
            raise ValueError(f"{where}: labels must be text")
        for literal in text.split():
            if literal.lstrip("!") not in PROPOSITIONS:
                raise ValueError(f"{where}: unknown label '{literal.lstrip('!')}'")

    if not isinstance(data, dict):
        raise ValueError("expectations must be an object keyed by scenario/variant/driver")
    for key, entry in data.items():
        if len(key.split("/")) != 3:
            raise ValueError(f"'{key}': key must be scenario/variant/driver")
        for i, phase in enumerate(entry.get("phases", [])):
            if not isinstance(phase.get("name"), str) or not isinstance(phase.get("optional", False), bool):
                raise ValueError(f"{key}, phase {i + 1}: needs a name and an optional flag")
            at = phase.get("at")
            if at is not None and (isinstance(at, bool) or not isinstance(at, (int, float)) or at < 0):
                raise ValueError(f"{key}, phase {i + 1}: the expected time must be a number of seconds")
            literals(phase.get("labels"), f"{key}, phase {i + 1}")
        for i, combo in enumerate(entry.get("never", [])):
            literals(combo, f"{key}, never {i + 1}")
        verdict = entry.get("verdict", {})
        if not isinstance(verdict.get("completed", True), bool):
            raise ValueError(f"{key}: verdict.completed must be true or false")
        for rule in verdict.get("violations", []):
            if rule not in rules:
                raise ValueError(f"{key}: unknown rule '{rule}'")
        if verdict.get("waited", "nowhere") not in where_it_waited.states:
            raise ValueError(f"{key}: unknown halting place '{verdict.get('waited')}'")


def read(path: Path = FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def stamp(data: dict | None = None) -> str:
    """A short fingerprint of the saved expectations: it changes whenever they do."""
    text = json.dumps(read() if data is None else data, sort_keys=True)
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def write(data: dict, path: Path = FILE) -> None:
    check(data)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    reload(path)


def reload(path: Path = FILE) -> None:
    """(Re)fill EXPECTED and EXPECTED_VERDICT from the file."""
    EXPECTED.clear()
    EXPECTED_VERDICT.clear()
    for key, entry in read(path).items():
        k = tuple(key.split("/"))
        EXPECTED[k] = Expectation(
            tuple(Phase(p["name"], p["labels"], bool(p.get("optional")), p.get("at"))
                  for p in entry.get("phases", [])),
            tuple(entry.get("never", [])),
        )
        v = entry.get("verdict", {})
        EXPECTED_VERDICT[k] = Verdict(v.get("completed", True), tuple(v.get("violations", [])),
                                      v.get("waited", "nowhere"))


reload()

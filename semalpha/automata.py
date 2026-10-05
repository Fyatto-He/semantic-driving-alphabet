"""Small deterministic automata that read the label sequence of a run.

An automaton is in exactly one state. At every frame it looks at the set of labels that
are true and may move to another state. Its transitions are tried in the order written;
the first whose condition holds is taken, and if none holds it stays where it is. So for
any state and any set of labels there is exactly one next state: it is a DFA whose
alphabet is the set of all label combinations.

A condition is a list of labels that must be on (``name``) or off (``!name``), the same
notation as in expected.py. "A or B" is written as two transitions to the same state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, List, Set, Tuple


def holds(condition: str, labels: FrozenSet[str]) -> bool:
    for literal in condition.split():
        if literal.startswith("!"):
            if literal[1:] in labels:
                return False
        elif literal not in labels:
            return False
    return True


@dataclass(frozen=True)
class Automaton:
    name: str
    rule: str                                             # what it checks, in plain words
    initial: str
    transitions: Dict[str, Tuple[Tuple[str, str], ...]]   # state -> ((condition, next state), ...)
    good: Tuple[str, ...] = ()                            # states meaning "achieved"
    bad: Tuple[str, ...] = ()                             # states meaning "rule broken" (never left)
    kind: str = "rule"                                    # "rule", "task" or "branch"

    @property
    def states(self) -> List[str]:
        """All states: the initial one, then the others that have transitions, in the order
        written, then states that are only ever arrived at (such as `violated`). Writing the
        transitions in their natural order therefore gives a natural left-to-right drawing."""
        seen = [self.initial]
        for state in self.transitions:
            if state not in seen:
                seen.append(state)
        for moves in self.transitions.values():
            for _, nxt in moves:
                if nxt not in seen:
                    seen.append(nxt)
        return seen

    def step(self, state: str, labels: FrozenSet[str]) -> str:
        for condition, nxt in self.transitions.get(state, ()):
            if holds(condition, labels):
                return nxt
        return state

    def run(self, label_sequence: Iterable[FrozenSet[str]]) -> List[str]:
        """The state after reading each frame."""
        state, visited = self.initial, []
        for labels in label_sequence:
            state = self.step(state, labels)
            visited.append(state)
        return visited

    def labels_used(self) -> Set[str]:
        return {literal.lstrip("!") for moves in self.transitions.values()
                for condition, _ in moves for literal in condition.split()}

    def to_mermaid(self) -> str:
        """State diagram in Mermaid syntax (GitHub renders it inside Markdown)."""
        lines = ["stateDiagram-v2", f"    [*] --> {self.initial}"]
        for state, moves in self.transitions.items():
            for condition, nxt in moves:
                text = " and ".join(("not " + lit[1:]) if lit.startswith("!") else lit
                                    for lit in condition.split())
                lines.append(f"    {state} --> {nxt}: {text}")
        for state in self.good:
            lines.append(f"    {state} --> [*]")
        return "\n".join(lines)

"""A recorded run: one world snapshot per simulation step, saved as JSON.

Snapshots hold raw simulator state only (no labels), so labeling functions can be
changed and re-run without simulating again.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from semalpha import ROOT


@dataclass
class Vehicle:
    x: float           # centre of the vehicle, metres
    y: float
    yaw: float         # radians, 0 = +x axis, counter-clockwise positive
    speed: float       # m/s along the heading
    length: float
    width: float


@dataclass
class Frame:
    t: float                              # simulation time, seconds
    vehicles: Dict[str, Vehicle]          # every vehicle in the world, including the ego
    signals: Dict[str, str]               # signal actor id -> GO | CAUTION | STOP | UNKNOWN
    events: Optional[List[str]] = None    # SMARTS events for the ego (agent-driven runs only)
    action: Optional[float] = None        # target speed commanded at this state (scripted runs only)


@dataclass
class Run:
    scenario: str
    variant: str
    driver: str
    story: str                 # the decision branch this variant stages
    net_file: str              # SUMO network the run used, relative to the project folder
    ego_route: List[str]       # edge ids
    dt: float
    ego_end: float = 70.0      # metres into the last route edge where the ego's route ends
    frames: List[Frame] = field(default_factory=list)

    @property
    def net_path(self) -> Path:
        return ROOT / self.net_file    # an absolute net_file (older recordings) is used as is

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        for frame in data["frames"]:   # keep files small and diff-friendly
            frame["t"] = round(frame["t"], 3)
            for v in frame["vehicles"].values():
                for k, val in v.items():
                    v[k] = round(val, 3)
        path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        return path

    @staticmethod
    def load(path: Path) -> "Run":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        frames = [
            Frame(
                t=f["t"],
                vehicles={k: Vehicle(**v) for k, v in f["vehicles"].items()},
                signals=f["signals"],
                events=f.get("events"),
                action=f.get("action"),
            )
            for f in data.pop("frames")
        ]
        return Run(**data, frames=frames)

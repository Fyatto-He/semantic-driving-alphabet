"""Semantic alphabets for automata-guided driving: SMARTS research prototype."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAPS = Path(__file__).resolve().parent / "maps"
BUILD = ROOT / "build"      # generated networks and SMARTS scenario folders
OUTPUTS = ROOT / "outputs"  # recorded runs, traces, figures

EGO = "ego"  # id of the ego vehicle in every run, whoever drives it

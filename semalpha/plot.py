"""Figures: map drawing shared by every plot, and the scenario overview sheet.

    python -m semalpha.plot        # writes docs/figures/scenarios.png and docs/figures/traces.png
"""
from __future__ import annotations

import math
from typing import Sequence, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as PolygonPatch
from shapely.geometry import LineString

from semalpha import ROOT
from semalpha.build import build_map
from semalpha.mapinfo import MapInfo, RoutePath
from semalpha.scenarios import SCENARIOS

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SOFT = "#52514e"
ROAD = "#e3e2de"
ROAD_EDGE = "#c9c8c2"
EGO_COLOR = "#2a78d6"     # categorical slot 1
OTHER_COLOR = "#eb6834"   # categorical slot 2


def draw_map(ax, mapinfo: MapInfo) -> None:
    """Road surface: every lane as a strip of its own width, junction areas filled in."""
    for lane in mapinfo.all_lanes():
        shape = mapinfo.lane_shape(lane)
        if len(shape) < 2:
            continue
        strip = LineString(shape).buffer(mapinfo.lane_width(lane) / 2, cap_style="flat")
        ax.add_patch(PolygonPatch(list(strip.exterior.coords), facecolor=ROAD,
                                  edgecolor=ROAD_EDGE, linewidth=0.4, zorder=1))
    for junction in mapinfo.junctions:
        poly = mapinfo.junction_polygon(junction)
        ax.add_patch(PolygonPatch(list(poly.exterior.coords), facecolor=ROAD,
                                  edgecolor="none", zorder=1.1))
    ax.set_aspect("equal")
    ax.set_facecolor(SURFACE)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def draw_route(ax, path: RoutePath, color: str, width: float, window, zorder: float = 3) -> None:
    """A route's centre line with one arrowhead where it leaves the window."""
    xs, ys = path.line.xy
    ax.plot(xs, ys, color=color, linewidth=width, solid_capstyle="round", zorder=zorder)
    (x0, x1), (y0, y1) = window
    inside = [s for s in _frange(0, path.length, 1.0)
              if x0 + 4 < path.point_at(s)[0] < x1 - 4 and y0 + 4 < path.point_at(s)[1] < y1 - 4]
    if inside:
        tip, tail = path.point_at(inside[-1]), path.point_at(inside[-1] - 1.5)
        ax.annotate("", xy=tip, xytext=tail, zorder=zorder + 0.1,
                    arrowprops=dict(arrowstyle="-|>", color=color, lw=width, mutation_scale=9 + 3 * width))


def _frange(a: float, b: float, step: float):
    n = int((b - a) / step)
    return [a + i * step for i in range(n + 1)]


def _normal_tick(ax, path: RoutePath, s: float, half: float, **kw) -> None:
    """A short line across the route at distance s (used for stop / yield lines)."""
    x, y = path.point_at(s)
    xa, ya = path.point_at(s - 0.5)
    dx, dy = x - xa, y - ya
    n = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / n, dx / n
    ax.plot([x - nx * half, x + nx * half], [y - ny * half, y + ny * half], **kw)


def _label_in_free_space(ax, mapinfo: MapInfo, xy, text: str, taken: list, reach: float = 15.0) -> None:
    """Label a point with a leader line, putting the text wherever is furthest from roads and other labels."""
    roads = [LineString(mapinfo.lane_shape(l)) for l in mapinfo.all_lanes() if len(mapinfo.lane_shape(l)) > 1]
    best, best_score = None, -1.0
    for k in range(16):
        angle = 2 * math.pi * k / 16
        cand = (xy[0] + reach * math.cos(angle), xy[1] + reach * math.sin(angle))
        pt = LineString([cand, cand]).centroid
        score = min([r.distance(pt) for r in roads] + [math.dist(cand, t) for t in taken])
        if score > best_score:
            best, best_score = cand, score
    taken.append(best)
    ax.annotate(text, xy, xytext=best, fontsize=7.5, color=INK_SOFT, zorder=5,
                ha="left" if best[0] >= xy[0] else "right", va="center",
                arrowprops=dict(arrowstyle="-", color=INK_SOFT, lw=0.6, shrinkA=1, shrinkB=3))


def scenario_overview(out=ROOT / "docs" / "figures" / "scenarios.png"):
    scenarios = list(SCENARIOS.values())
    fig, axes = plt.subplots(1, len(scenarios), figsize=(3.5 * len(scenarios), 4.3), facecolor=SURFACE)
    half = 34.0
    for ax, scenario in zip(axes, scenarios):
        mapinfo = MapInfo(build_map(scenario.map))
        ego = mapinfo.route_path(scenario.ego_route)
        first = ego.junctions[0]
        cx, cy = ego.point_at((first.entry_s + ego.junctions[-1].exit_s) / 2)
        window = ((cx - half, cx + half), (cy - half, cy + half))
        draw_map(ax, mapinfo)
        seen = set()
        for variant in scenario.variants:
            for car in variant.cars:
                if car.route not in seen:
                    seen.add(car.route)
                    draw_route(ax, mapinfo.route_path(car.route), OTHER_COLOR, 1.4, window, zorder=2.5)
        draw_route(ax, ego, EGO_COLOR, 2.6, window)
        control = first.link.control
        line_name = {"stop": "stop line", "yield": "yield line", "signal": "signal stop line"}.get(control, "entry line")
        _normal_tick(ax, ego, first.entry_s, 1.9, color=INK, linewidth=2.2, zorder=4, solid_capstyle="butt")
        taken = []
        _label_in_free_space(ax, mapinfo, ego.point_at(first.entry_s), line_name, taken)
        if first.waiting_s is not None:
            wx, wy = ego.point_at(first.waiting_s)
            ax.plot([wx], [wy], marker="o", markersize=6, markerfacecolor=SURFACE,
                    markeredgecolor=INK, markeredgewidth=1.4, zorder=5)
            _label_in_free_space(ax, mapinfo, (wx, wy), "waiting point", taken)
        ax.set_xlim(*window[0])
        ax.set_ylim(*window[1])
        ax.set_title(scenario.name, fontsize=10, color=INK, loc="left", pad=6)
        ax.text(0, -0.03, f"{scenario.map} map, {len(scenario.variants)} variant{'s' if len(scenario.variants) > 1 else ''}", transform=ax.transAxes,
                fontsize=7.5, color=INK_SOFT, va="top")
    handles = [
        plt.Line2D([], [], color=EGO_COLOR, linewidth=2.6, label="ego route"),
        plt.Line2D([], [], color=OTHER_COLOR, linewidth=1.4, label="routes of staged background cars (all variants)"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=2, frameon=False, fontsize=8.5,
               labelcolor=INK_SOFT, bbox_to_anchor=(0.5, 0.0))
    fig.subplots_adjust(left=0.01, right=0.99, top=0.92, bottom=0.13, wspace=0.05)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=170, facecolor=SURFACE)
    plt.close(fig)
    return out




# ---- label timelines -----------------------------------------------------------------------

GROUP_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]   # categorical slots 1-6, fixed order
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
WARNING = "#fab219"

REPRESENTATIVE = (
    ("t_stop_left", "wait_for_gap", "sumo"),
    ("t_major_left", "oncoming_then_gap", "sumo"),
    ("signal_straight", "yellow_far", "sumo"),
    ("roundabout", "yield_to_circulating", "sumo"),
    ("t_stop_left", "wait_for_gap", "enter_too_early"),
    ("signal_straight", "red_then_green", "run_red"),
)


def draw_timeline(ax, trace, expectation, match) -> None:
    """One row per proposition, a bar wherever it is true; numbered lines mark the expected phases."""
    from semalpha.predicates import GROUP, PROPOSITIONS

    names = list(PROPOSITIONS)
    groups = list(dict.fromkeys(GROUP.values()))
    dt = trace.run.dt
    t0, t1 = trace.times[0], trace.times[-1] + dt
    for a, b in match.unexplained:
        ax.axvspan(a, b, color=WARNING, alpha=0.25, linewidth=0, zorder=0)
    for row, name in enumerate(names):
        color = GROUP_COLORS[groups.index(GROUP[name])]
        start = None
        for i, labels in enumerate(trace.labels + [frozenset()]):
            holds = name in labels
            if holds and start is None:
                start = trace.times[i]
            if not holds and start is not None:
                ax.barh(row, trace.times[i - 1] + dt - start, left=start, height=0.5, color=color, linewidth=0, zorder=2)
                start = None
        if row and GROUP[names[row - 1]] != GROUP[name]:
            ax.axhline(row - 0.5, color=AXIS, linewidth=0.6, zorder=1)
    number = 0
    for phase, t in zip(expectation.phases, match.reached):
        number += 1
        if t is None:
            continue
        ax.axvline(t, color=AXIS, linewidth=0.7, zorder=1)
        ax.text(t, -1.05, str(number), fontsize=7, color=INK_SOFT, ha="center", va="center")
    ax.set_ylim(len(names) - 0.4, -1.6)
    ax.set_xlim(t0, t1)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=7, color=INK_SOFT)
    ax.tick_params(axis="both", length=0, labelsize=7, colors=INK_SOFT)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:g} s")
    ax.grid(axis="x", color=GRID, linewidth=0.6, zorder=0)
    ax.set_facecolor(SURFACE)
    for spine in ax.spines.values():
        spine.set_visible(False)


def trace_figure(runs=REPRESENTATIVE, out=ROOT / "docs" / "figures" / "traces.png"):
    import textwrap

    from semalpha.expected import EXPECTED
    from semalpha.label import compare, label_run, run_file
    from semalpha.predicates import GROUP
    from semalpha.record import Run

    cols = 2
    rows = (len(runs) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(7.6 * cols, 4.5 * rows), facecolor=SURFACE)
    for ax, key in zip(axes.flat, runs):
        trace = label_run(Run.load(run_file(*key)))
        expectation = EXPECTED[key]
        match = compare(trace, expectation)
        draw_timeline(ax, trace, expectation, match)
        verdict = {"match": "matches expectation", "match*": "matches, with an unexplained stretch (shaded)",
                   "MISMATCH": "differs from expectation"}[match.verdict]
        ax.set_title(f"{key[0]} / {key[1]} / {key[2]}", fontsize=9.5, color=INK, loc="left", pad=16)
        ax.text(1.0, 1.045, verdict, transform=ax.transAxes, fontsize=7.5, color=INK_SOFT, ha="right")
        phases = "   ".join(
            f"{i + 1} {'(' + p[0] + ')' if len(p) > 2 else p[0]}"
            for i, (p, t) in enumerate(zip(expectation.phases, match.reached)) if t is not None)
        ax.text(0, -0.085, "\n".join(textwrap.wrap("Expected phases:  " + phases, 112)), transform=ax.transAxes,
                fontsize=6.8, color=INK_SOFT, va="top")
    for ax in list(axes.flat)[len(runs):]:
        ax.set_visible(False)
    groups = list(dict.fromkeys(GROUP.values()))
    handles = [plt.Rectangle((0, 0), 1, 1, color=c, label=g) for g, c in zip(groups, GROUP_COLORS)]
    fig.legend(handles=handles, loc="lower center", ncol=len(groups), frameon=False, fontsize=8.5,
               labelcolor=INK_SOFT, bbox_to_anchor=(0.5, 0.0), handlelength=1.4, handleheight=0.6)
    fig.subplots_adjust(left=0.105, right=0.985, top=0.94, bottom=0.085, wspace=0.34, hspace=0.42)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=140, facecolor=SURFACE)
    plt.close(fig)
    return out


if __name__ == "__main__":
    print(scenario_overview())
    print(trace_figure())

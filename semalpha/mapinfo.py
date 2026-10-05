"""Static map semantics read from a SUMO network file.

SMARTS' own RoadMap API covers lane geometry and connectivity but not right-of-way,
so this reads the network with sumolib directly. Everything here is map-only: it
never looks at vehicles.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from shapely.geometry import LineString, Point, Polygon

from smarts.core.utils.sumo_utils import sumolib  # puts SUMO's tools on sys.path

# How SUMO marks the control of one movement ("link") through a junction.
_CONTROL_BY_STATE = {
    "M": "priority",     # major: has right of way over crossing minor links
    "m": "yield",        # minor: must give way, need not stop
    "s": "stop",         # minor with a STOP sign
    "w": "allway_stop",
    "=": "equal",        # unregulated / right-before-left
    "Z": "zipper",
}


@dataclass(frozen=True)
class Link:
    """One permitted movement through a junction, from an approach lane to an exit lane."""

    junction: str
    index: int                 # row/column of this link in the junction's right-of-way table
    from_lane: str
    to_lane: str
    via: Tuple[str, ...]       # internal lanes driven through, in order
    direction: str             # 's' straight, 'l' left, 'r' right, 't' U-turn ('L'/'R' = partial)
    control: str               # priority | yield | stop | allway_stop | equal | zipper | signal
    signal: Optional[str]      # id of the SMARTS signal actor controlling this link, if any

    @property
    def has_waiting_point(self) -> bool:
        """True if the movement is split by an in-junction waiting position (typical for left turns)."""
        return len(self.via) > 1


@dataclass(frozen=True)
class JunctionOnRoute:
    """Where a route passes through a junction, in metres along the route."""

    link: Link
    entry_s: float                  # stop/yield line: end of the approach lane
    exit_s: float                   # start of the exit lane
    waiting_s: Optional[float]      # in-junction waiting position, if the link has one


class RoutePath:
    """A route flattened into one centre line, so a position can be expressed as distance along the route."""

    def __init__(self, lanes: Sequence[str], shapes: Sequence[Sequence[Tuple[float, float]]],
                 junctions: Sequence[Tuple[Link, int, int]]):
        self.lanes = list(lanes)
        points: List[Tuple[float, float]] = []
        self.starts: List[float] = []
        length = 0.0
        for shape in shapes:
            self.starts.append(length)
            for p in shape:
                if points and _dist(points[-1], p) < 1e-6:
                    continue
                if points:
                    length += _dist(points[-1], p)
                points.append((p[0], p[1]))
        self.length = length
        self.line = LineString(points)
        ends = self.starts[1:] + [length]
        self.junctions = [
            JunctionOnRoute(
                link=link,
                entry_s=self.starts[first],
                exit_s=ends[last],
                waiting_s=ends[first] if link.has_waiting_point else None,
            )
            for link, first, last in junctions
        ]

    def locate(self, x: float, y: float) -> Tuple[float, float]:
        """(distance along the route, unsigned distance from its centre line)."""
        p = Point(x, y)
        return self.line.project(p), self.line.distance(p)

    def lane_at(self, s: float) -> str:
        for lane, start in zip(reversed(self.lanes), reversed(self.starts)):
            if s >= start:
                return lane
        return self.lanes[0]

    def point_at(self, s: float) -> Tuple[float, float]:
        p = self.line.interpolate(max(0.0, min(s, self.length)))
        return p.x, p.y


class MapInfo:
    def __init__(self, net_file: Path | str):
        self.net_file = Path(net_file)
        self.net = sumolib.net.readNet(str(net_file), withInternal=True)
        self._links_by_junction: Dict[str, List[Link]] = {}
        self._link_by_internal_lane: Dict[str, Link] = {}
        for node in self.net.getNodes():
            links = []
            for conn in node.getConnections():
                if conn.getJunctionIndex() < 0:   # internal continuation of another link
                    continue
                link = self._make_link(node, conn)
                links.append(link)
                for lane in link.via:
                    self._link_by_internal_lane[lane] = link
            if links:
                self._links_by_junction[node.getID()] = sorted(links, key=lambda l: l.index)

    # ---- junction links and right of way -------------------------------------------------

    def _make_link(self, node, conn) -> Link:
        via = []
        nxt = conn.getViaLaneID()
        while nxt:
            via.append(nxt)
            outgoing = self.net.getLane(nxt).getOutgoing()
            nxt = outgoing[0].getViaLaneID() if outgoing else ""
        tls = conn.getTLSID()
        return Link(
            junction=node.getID(),
            index=conn.getJunctionIndex(),
            from_lane=conn.getFromLane().getID(),
            to_lane=conn.getToLane().getID(),
            via=tuple(via),
            direction=conn.getDirection(),
            control="signal" if tls else _CONTROL_BY_STATE.get(conn.getState(), conn.getState()),
            # SMARTS names signal actors "tls_<traffic light id>-<link index in the light's program>"
            signal=f"tls_{tls}-{conn.getTLLinkIndex()}" if tls else None,
        )

    @property
    def junctions(self) -> List[str]:
        """Ids of real junctions (places where movements can conflict)."""
        return [j for j, links in self._links_by_junction.items() if len(links) > 1]

    def links(self, junction: str) -> List[Link]:
        return self._links_by_junction.get(junction, [])

    def links_from(self, lane_id: str) -> List[Link]:
        """Every movement a vehicle on this approach lane could take."""
        node = self.net.getLane(lane_id).getEdge().getToNode().getID()
        return [l for l in self.links(node) if l.from_lane == lane_id]

    def link_points(self, link: Link) -> List[Tuple[float, float]]:
        """Centre line of a movement from its entry line to the start of its exit lane."""
        return [p for lane in link.via for p in self.lane_shape(lane)]

    def lanes_into(self, junction: str) -> List[str]:
        """Approach lanes of a junction."""
        return sorted({l.from_lane for l in self.links(junction)})

    def link_of_internal_lane(self, lane_id: str) -> Optional[Link]:
        return self._link_by_internal_lane.get(lane_id)

    def paths_cross(self, a: Link, b: Link) -> bool:
        """True if the two movements cross or merge inside the junction."""
        if a.junction != b.junction or a.index == b.index:
            return False
        return self.net.getNode(a.junction).areFoes(a.index, b.index)

    def must_yield(self, a: Link, b: Link) -> bool:
        """True if the junction's static rules make movement `a` give way to movement `b`.

        This is the sign/priority rule only. For signal-controlled links it is the rule that
        applies when both have green (e.g. a permissive left turn yields to oncoming traffic).
        """
        if a.junction != b.junction or a.index == b.index:
            return False
        node = self.net.getNode(a.junction)
        return node._prohibits[a.index][-(b.index + 1)] == "1"

    @cached_property
    def roundabout_edges(self) -> frozenset:
        return frozenset(e for rb in self.net.getRoundabouts() for e in rb.getEdges())

    def roundabout_nodes(self, junction: str) -> Tuple[str, ...]:
        """All junctions of the roundabout this junction belongs to (empty if it is not on one)."""
        for rb in self.net.getRoundabouts():
            if junction in rb.getNodes():
                return tuple(rb.getNodes())
        return ()

    # ---- lanes ---------------------------------------------------------------------------

    def lane_shape(self, lane_id: str) -> List[Tuple[float, float]]:
        return [(p[0], p[1]) for p in self.net.getLane(lane_id).getShape()]

    def lane_width(self, lane_id: str) -> float:
        return self.net.getLane(lane_id).getWidth()

    def speed_limit(self, lane_id: str) -> float:
        return self.net.getLane(lane_id).getSpeed()

    def is_internal(self, lane_id: str) -> bool:
        return lane_id.startswith(":")

    def all_lanes(self) -> List[str]:
        return [l.getID() for e in self.net.getEdges(withInternal=True) for l in e.getLanes()]

    def junction_polygon(self, junction: str) -> Polygon:
        return Polygon([(p[0], p[1]) for p in self.net.getNode(junction).getShape()])

    # ---- routes --------------------------------------------------------------------------

    def route_path(self, edges: Sequence[str], lane_index: int = 0) -> RoutePath:
        """Lane-level path for a route given as a list of edge ids."""
        lane = self.net.getEdge(edges[0]).getLane(lane_index)
        lanes = [lane.getID()]
        junctions = []
        for nxt in edges[1:]:
            conns = [c for c in lane.getOutgoing() if c.getTo().getID() == nxt]
            if not conns:
                raise ValueError(f"no connection from lane {lane.getID()} to edge {nxt}")
            conn = conns[0]
            link = next(l for l in self.links_from(lane.getID())
                        if l.to_lane == conn.getToLane().getID())
            first = len(lanes)
            lanes += list(link.via)
            junctions.append((link, first, len(lanes) - 1))
            lane = conn.getToLane()
            lanes.append(lane.getID())
        return RoutePath(lanes, [self.lane_shape(l) for l in lanes], junctions)


def _dist(a, b) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def describe(mapinfo: MapInfo) -> str:
    """Human-readable table of every junction's movements and who gives way to whom."""
    out = []
    for junction in mapinfo.junctions:
        links = mapinfo.links(junction)
        out.append(f"junction {junction}")
        for a in links:
            row = "".join(
                "Y" if mapinfo.must_yield(a, b) else ("x" if mapinfo.paths_cross(a, b) else ".")
                for b in links
            )
            wait = " +waiting point" if a.has_waiting_point else ""
            out.append(
                f"  [{a.index:>2}] {a.from_lane:>10} -> {a.to_lane:<10} {a.direction} "
                f"{a.control:<9} {row}{wait}"
            )
    out.append("  (matrix: row vs column. Y = row gives way, x = paths cross and row has priority)")
    if mapinfo.roundabout_edges:
        out.append(f"roundabout edges: {sorted(mapinfo.roundabout_edges)}")
    return "\n".join(out)


if __name__ == "__main__":
    import sys

    from semalpha.build import build_map

    for name in sys.argv[1:]:
        print(f"== {name} ==")
        print(describe(MapInfo(build_map(name))))

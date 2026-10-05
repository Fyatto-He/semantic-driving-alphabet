# Semantic vocabulary v1 (implemented, under review at Checkpoint 3)

Derived from the traces in [traces.md](traces.md), implemented in `semalpha/`, and compared
against the expected sequences in `semalpha/expected.py` on 26 recorded runs.

## Rules

- A proposition states a fact about the world. It never states what the ego should do.
- Other cars are referred to by their relation to the ego, never by id.
- Other cars are judged from position, heading, speed and size only. Their routes are
  unknown: a car that could still take several movements is treated as possibly taking
  any of them.
- A proposition is true or false in a single frame. Memory belongs to the automaton.
- Every number lives in `semalpha/thresholds.yaml`.

## Layers and where they live

| Layer | What | File |
|---|---|---|
| 1 Helpers | distances, times, footprints, centre lines | `helpers.py`, `mapinfo.py` |
| 2 Relational predicates | facts about the ego and one junction or one other car | `relations.py` |
| 3 Propositions | the 19 true/false facts the automaton sees | `predicates.py` |

Terms: *the junction* is the one next on the ego's route or around the ego; a roundabout's
whole ring counts as one junction. A *movement* is one permitted path through a junction.
Two movements *share road* where their centre lines come closer than 2 m (two half-widths
of `conflict_half_width_m`).

## The 19 propositions

| Group | Proposition | True when | Thresholds |
|---|---|---|---|
| Progress | `approaching_junction` | the entry line is ahead, within the horizon, and the ego is not yet at it | `approach_horizon_m` 50, `entry_tolerance_m` 2 |
| | `at_entry_line` | the ego's front bumper is within the tolerance before the stop / yield / signal line | `entry_tolerance_m` 2 |
| | `in_junction` | the ego's front is past the entry line and its rear has not left the junction | none |
| | `in_waiting_area` | the ego is inside but not yet on road shared with any movement that may currently move (movements held at red do not count) | `conflict_half_width_m` 1 |
| Control | `stop_sign` | the ego's movement is stop-controlled | none |
| | `signal_go`, `signal_caution`, `signal_stop` | the aspect shown to the ego's movement; all false without a signal | none |
| Interaction | `conflict_present` | some car's possible path meets the ego's remaining path and neither has passed that place | `commit_lateral_m` 1, `commit_heading_deg` 20 |
| | `ego_has_priority` | the rules give the ego right of way over every such car | none |
| | `gap_safe` | going now, the ego and every such car would use the shared road at least the margin apart | `gap_margin_s` 2, `gap_ego_accel` 2 |
| | `others_can_yield` | every car that owes the ego priority whichever way it goes can still stop short of the ego's path | `others_stop_decel` 4.5 |
| Occupancy | `path_blocked` | a car that is not heading along the ego's path is physically on it inside the junction | `same_direction_deg` 60 |
| | `exit_clear` | no slow car occupies the space the ego needs beyond the junction | `exit_space_m` 2, `exit_blocking_speed` 1 |
| Ego motion | `ego_stopped` | the ego's speed is below the tolerance | `stopped_speed` 0.1 |
| | `can_stop_before_entry` | at a comfortable deceleration the ego can still halt before the line | `comfortable_decel` 3 |
| Terminal | `collision`, `off_road`, `goal_reached` | SMARTS event, or the geometric equivalent | `goal_tolerance_m` 3 |

The three progress propositions `approaching_junction`, `at_entry_line`, `in_junction` are
mutually exclusive. With no conflicting car, `conflict_present` is false and
`ego_has_priority`, `gap_safe`, `others_can_yield` are true.

### How the interaction propositions are computed

1. **Which cars count.** Cars on a lane leading into the junction, or inside it. On a
   roundabout this includes cars that would reach the ego's path after passing further
   ring junctions, up to three quarters of the ring.
2. **What a car may do.** On an approach lane: every movement from that lane. Inside the
   junction: every movement whose centre line it is within 1 m and 20° of.
3. **Conflict.** A possible movement conflicts if the map says it crosses or merges with
   the ego's movement and neither car is past the shared road. For a merge the other car
   is past once it is wholly beyond the point where the paths join.
4. **Priority.** From the map's right-of-way table. A signal overrides it: a car facing
   red has no priority, except that a car already inside keeps it over cars still outside.
   The ego is never credited with priority while its own signal is red.
5. **Gap.** Times are computed for the ego going now (accelerating at 2 m/s² up to the
   turn's speed limit) and the other car keeping its current speed. The gap is safe if
   either car clears the shared road at least 2 s before the other reaches it. A
   stationary car never arrives.

## What changed between the draft and v1

After the first comparison with the expected sequences:

| Change | Why |
|---|---|
| A merging car counts as past once wholly beyond the join point | Before, the ego was labelled as entering 0.2 s "too early" whenever it followed a car into a merge |
| Roundabout: possible paths follow the ring through later junctions | A car entering one arm upstream was not seen as a possible conflict until almost at the ego's entry |
| `in_waiting_area` ignores movements held at red | At the signal, the simulator's own waiting position was labelled as past the point of no return |
| `path_blocked` ignores cars heading within 60° of the ego's path | A car ahead that turned off the ring was briefly counted as blocking |
| `others_can_yield` added, restricted to cars that owe priority under every possible movement | Draft question Q3; the restriction stops it reacting to hypothetical movements |

## Evidence from the 26 runs

`python -m semalpha.label --stats`:

| Proposition | Share of time true | Value changes | Blips (≤ 0.3 s) | Note |
|---|---:|---:|---:|---|
| `approaching_junction` | 24% | 52 | 0 | |
| `at_entry_line` | 16% | 52 | 13 | brief whenever the ego drives through without stopping, by design |
| `in_junction` | 21% | 50 | 0 | |
| `in_waiting_area` | 7% | 52 | 1 | |
| `stop_sign` | 22% | 16 | 0 | |
| `signal_go` / `caution` / `stop` | 5% / 1% / 8% | 12 / 4 / 6 | 1 / 0 / 0 | |
| `conflict_present` | 28% | 36 | 0 | |
| `ego_has_priority` | 75% | 32 | 0 | |
| `gap_safe` | 74% | 42 | 2 | flickers when another car changes speed (roundabout approach) |
| `others_can_yield` | 100% | 0 | 0 | **never false: not exercised** |
| `path_blocked` | 1% | 29 | 1 | almost always coincides with an unsafe gap |
| `exit_clear` | 100% | 0 | 0 | **never false: not exercised** |
| `ego_stopped` | 14% | 32 | 5 | the simulator's stop at an empty stop sign lasts one frame |
| `can_stop_before_entry` | 41% | 46 | 6 | chatters when the ego brakes along the threshold |
| `collision` / `off_road` / `goal_reached` | 0% / 0% / 1% | 2 / 0 / 24 | 0 | `off_road` not exercised |

How the three main interaction propositions combine (seconds over all runs):

| `conflict_present` | `ego_has_priority` | `gap_safe` | Seconds | Reading |
|:-:|:-:|:-:|---:|---|
| no | yes | yes | 382 | nobody relevant |
| yes | no | no | 126 | someone who outranks the ego is too close |
| yes | yes | no | 11 | timing is tight, but the other car owes the ego priority |
| yes | no | yes | 8 | someone outranks the ego but is far enough |
| yes | yes | yes | 4 | someone is around; the ego has priority and time |

## Threshold sensitivity

`python -m semalpha.label --set name=value`:

| Setting | Result on 26 runs |
|---|---|
| defaults | 23 match, 3 match with an unexplained stretch |
| `comfortable_decel` 4.5 instead of 3 | 25 match, 1 with an unexplained stretch |
| `gap_other_at_least_limit` true | 23 / 3; the roundabout flicker drops from 0.8 s to 0.2 s |
| `gap_margin_s` 1 | 1 run differs: an entry in front of a possible conflict is no longer called unsafe |
| `gap_margin_s` 1.5 | 23 / 3; the roundabout flicker grows to 2.7 s |
| `gap_margin_s` 2.5 | 21 / 5; in two runs the reference driver moves off 0.2 s before the label says safe |
| `gap_margin_s` 3 | 2 runs differ for the same reason: the label never turns safe before the ego is already in |

## Intentionally left out

| Concept | Why |
|---|---|
| Decisions: `should_go`, `must_yield`, `need_to_stop` | The automaton decides; the alphabet describes. |
| Raw numbers: distances, speeds, coordinates, times | Not semantic; they live in helpers and thresholds. |
| Vehicle ids | Not relational. |
| Junction type: `is_t_junction`, `is_roundabout` | Would tie automata to map shape; control and priority already carry what matters. |
| `yield_sign` | Its only effect is on who outranks whom, which `ego_has_priority` already states. A stop sign differs because it obliges a stop on an empty road. |
| Direction of the other car: `from_left`, `oncoming` | Does not change behaviour once conflict and priority are known. |
| The ego's manoeuvre: `turning_left` | It is the task, not an observation; its consequences appear through the conflicts. |
| Memory: `has_stopped`, `was_green_on_entry`, `arrived_first` | Automaton state. `arrived_first` returns with the all-way stop in wave two. |
| Other cars' true routes or turn signals | Ruled out: observable-only. SMARTS has no turn signals. |
| Lane-level predicates: `in_lane`, `ahead_of`, `gap_safe(target_lane)`, a car ahead | First-wave maps have one lane per direction and no queues. They return with bus lanes and multi-lane roads. |
| Visibility and occlusion | SMARTS gives perfect state, so they could not be validated. |
| Speeding, comfort, lane-keeping quality | Quality of execution rather than junction reasoning. |

## Open points for review

1. **`can_stop_before_entry`**: with 3 m/s² it turns false for 2 to 3 s while the reference
   driver is in fact braking to a stop, because that driver brakes late at up to 4.5 m/s².
2. **`gap_safe` and the other car's speed**: judged at the other car's current speed, the
   label flips when that car slows for a turn and speeds up again.
3. **`others_can_yield`, `exit_clear`, `off_road`** are never false in any run. They need a
   variant that exercises them (a car running its stop sign, a blocked exit) or should go.
4. **`path_blocked`** carries almost no information beyond `gap_safe` in these runs.
5. **`conflict_present`** separates "nobody relevant" from "someone around but fine" for
   only 4 s in total. An automaton may not need the distinction.
6. **`has_priority` for an ego inside on red** is always false, which also covers the
   lawful case of an ego that entered on green and is still waiting inside when the
   lights change. Telling the two apart needs memory of the signal at entry.

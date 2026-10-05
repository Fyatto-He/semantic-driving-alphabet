# Design log

Short record of decisions that shape the vocabulary and the experiments. Newest last.

## 2026-10-04: Checkpoint 1 decisions

- **Platform**: native Windows, SMARTS 2.0.1, Python 3.10. Two Unix-only snippets in
  SMARTS are patched by `scripts/patch_smarts_windows.py`.
- **First wave**: stop-sign T-junction left turn, unprotected left from the main road
  (same map), signalized four-way, roundabout.
- **Deferred**: all-way stop, median, bus lane, one-way, dead end (wave two); U-turn,
  train crossing, yellow box (later). **Dropped**: three-point turn.
- **Other cars' intent is not observable.** Predicates may use only position, heading,
  speed and size of other cars. A car that could still take several movements is treated
  as possibly taking any of them. Their true routes are available in SUMO but are not used.

## 2026-10-04: Scenario infrastructure

- **Maps are built without U-turn links** (`no-turnarounds`). With U-turns deferred, the
  extra links would make every approaching car a possible conflict with everything under
  the observable-only rule.
- **Two trajectory sources.** SUMO's driver is the rule-following reference. A scripted,
  open-loop ego (speed only, blind to traffic) stages violations and unsafe entries. The
  script is blind on purpose, so the driver never depends on the labels being validated.
- **The reference driver knows more than a human.** SUMO uses each car's true route, so in
  `other_turns_off` and `circulating_exits` it goes immediately where a human would wait.
  Those variants also have a scripted "wait until it is visible" run for comparison.
- **Runs store raw state only**, one world snapshot per step. Labels are computed offline,
  so a vocabulary change never needs a new simulation.
- **The ego's route ends 70 m into its last edge**, short of the map boundary, because
  driving off the end of the map raises spurious `on_shoulder` events.

## 2026-10-04: Vocabulary draft v0 (awaiting review)

See [vocabulary.md](vocabulary.md). Three layers: helpers, relational predicates, and
18 ego-centred propositions. Open questions Q1–Q14 are listed there.

## 2026-10-04: Checkpoint 2 decisions

All draft defaults accepted (Q1 to Q14), including the added proposition
`others_can_yield`. The user asked for the expected label sequence to be written down for
every run and compared with what the labeling functions produce.

## 2026-10-04: Labeling functions, first comparison

`semalpha/expected.py` was written before any labeling code existed. First comparison of
the 26 runs: 12 matched, 11 reached every milestone with unexplained stretches, 3 differed.

Changes to the labeling functions (the definition was wrong or incomplete):

- **Merging.** A merging car now counts as past once it is wholly beyond the point where
  the paths join. Before, it stayed a conflict until it had left the junction, so an ego
  following it in was labelled as entering too early.
- **Roundabout scope.** A car's possible paths now continue through later ring junctions
  (at most three quarters of the ring). Before, a car entering one arm upstream was not a
  possible conflict until it was on the last ring segment before the ego's entry.
- **Waiting area under a signal.** `in_waiting_area` ignores movements currently held at
  red. Before, cross-street paths made the area end 0.3 m short of the map's own waiting
  point, and a correctly waiting ego was labelled as past the point of no return.
- **`path_blocked`.** Cars heading within 60 degrees of the ego's path are ignored
  (was 30), so a car ahead that turns off is not a blockage.
- **`others_can_yield`.** Only cars that owe the ego priority under every movement they may
  be making are considered. Before, an oncoming car that could hypothetically be turning
  made the proposition false.
- **Priority for an ego facing red** is always false. This departs from the Q5 default
  ("a car already inside keeps priority") for the ego only, because a frame cannot tell
  an ego that entered lawfully from one that ran the light.

Changes to the expectations (the expectation was too coarse, or the run changed):

- Optional in-between phases were added (moving off the line, nosing in, crossing the
  rest, red but still rolling). No milestone was removed.
- `roundabout/cut_in` was restaged. The first staging merged directly behind the ring car,
  which the labels correctly did not call an unsafe entry. The new staging enters in front
  and ends in a collision, so the expectation now ends with `collision`.
- `t_stop_left/overcautious`: "the road is free" is expressed as `gap_safe` alone, because
  `gap_safe` turns true 0.4 s before the last car counts as past.

Result: 23 match, 3 reach every milestone with an unexplained stretch. All three trace
to two thresholds (see vocabulary.md, "Open points for review"). Thresholds were left at
the approved defaults; none was tuned to make a run match.

Findings about the vocabulary:

- `others_can_yield`, `exit_clear` and `off_road` never change value in any run.
- `path_blocked` almost always coincides with an unsafe gap.
- `conflict_present` adds a distinction that lasts 4 s in total across all runs.
- A gap margin of 2 s is the only tested value consistent with both the reference driver's
  entries and the staged unsafe entries.

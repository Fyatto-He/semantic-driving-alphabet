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

## 2026-10-05: Checkpoint 3 decision

The labels and thresholds are kept exactly as they are for the current setting. More edge
cases will be needed to improve them further; that is deferred. Work moves to the automata.

## 2026-10-05: Rule automata, first version

**One rule set for every scenario, built from small automata** (`semalpha/rules.py`),
instead of one automaton per scene. The labels were designed to be independent of junction
type; a single rule set judging a stop sign, a signal and a roundabout is the direct test
of that. Small automata also say which rule was broken and when.

- `reach_goal` (task): approach, at_line, inside, cleared, done.
- Six rules, each with a `violated` state that is never left: `stop_at_stop_sign`,
  `obey_red_signal`, `stop_on_yellow_when_able`, `respect_right_of_way`, `no_collision`,
  `stay_on_road`.
- `where_it_waited` (branch): nowhere, at_line, inside, both.

Design choices:

- **Memory lives in the automata.** `obey_red_signal` remembers whether the ego was outside
  or inside, so being inside when the light turns red is lawful while entering on red is
  not. This is the distinction a single frame could not make (vocabulary open point 6).
- **Right of way is judged at the moment of committing**, that is, when the ego leaves the
  waiting area. A gap that turns unsafe afterwards is not held against the ego.
- **"Idle while free" is a plain measurement, not an automaton**, because it counts time.
- Transitions are ordered and conditions are conjunctions of labels, the same notation as
  the label expectations.

Result on the 26 recorded runs: 26 of 26 verdicts as written down beforehand
(`EXPECTED_VERDICT`). No lawful run raises a false alarm on any junction type; every
staged violation is caught by the intended rule.

Stability of the verdicts when a label threshold is changed (`verify --set`):

| Change | Verdicts as expected |
|---|---|
| gap margin 2.5, 3 or 4 s (default 2) | 26 |
| gap margin 1 or 1.5 s | 25: the entry in front of a possibly conflicting ring car is no longer a violation |
| comfortable braking 2 or 4.5 m/s² (default 3) | 26 |
| other car assumed at least at the speed limit | 26 |
| stopped below 0.5 m/s (default 0.1) | 26 |
| path half-width 1.3 m (default 1.0), commit heading 10° (default 20°) | 26 |
| entry-line tolerance 1 m (default 2) | 21: cars that stop 1.0 to 1.1 m short of the line are not seen as stopped at the line |

So the verdicts are much less sensitive to thresholds than the frame-by-frame label
sequences were. The one fragile number is the entry-line tolerance: it must be larger
than the distance at which drivers actually stop.

Limits of this result: no run breaks `stop_on_yellow_when_able` or `stay_on_road`; the
expectations were written with knowledge of the label sequences; the runs are the ones the
labels were developed on.

Labels no automaton needs so far: `approaching_junction`, `others_can_yield`,
`path_blocked`, `exit_clear`.

## 2026-10-05: Expectations become data, edited in the inspector

The user wants human testers to be able to change what a run is expected to show without
editing code or text files.

- **Expectations moved from Python to `semalpha/expectations.json`**, one entry per run
  with its phases, its never-combinations and its expected verdict. The conversion was
  mechanical; label and verdict results are identical before and after (23 match and
  3 partial; 26 of 26 verdicts). `expected.py` now only loads and checks the file.
  The shared building blocks of the Python version (`UP`, `CROSS`, ...) are expanded, so
  each run's phases are now independent: changing one run no longer changes others.
- **The inspector edits them.** Phases can be added, renamed, reordered, deleted and marked
  optional; labels are added from a list and flipped ON/OFF by clicking; a new label takes
  the value it has at the selected moment. Never-combinations and the expected verdict are
  edited the same way.
- **The page re-checks every edit itself**, with the same phase-walking rule as `label.py`
  written a second time in JavaScript. `selfCheck()` in the page compares the two on all
  runs; they agree on all 26. Two implementations of one rule is a risk: if `compare` in
  `label.py` is changed, the page's `evaluate` must be changed with it.
- **Saving.** `python -m semalpha.serve` serves the page on this computer and writes
  edits to `expectations.json`. The single-file page cannot write files, so it offers the
  edited file as a download. Unsaved edits are kept in the browser across reloads, tied to
  the version of the file they were based on.
- A run with nothing written is reported as having no expectation instead of failing.
- **Not done:** a mode that hides the current labels from a tester, so that expectations
  are written blind. Without it, a tester can see what the labels do while writing what
  they should do.

## 2026-10-05: Editor: taking changes back, expected times, phases anywhere

Asked for by the user after trying the editor.

- **Undo and redo**, plus **Revert this run**; "Discard changes" became "Discard all
  changes". Before, the only way back was to discard every edit in every run.
- **A phase can carry the time it is expected to begin** (`at`, in seconds). The comparison
  still walks the phases in order by their labels; a phase with a time is additionally
  checked for being reached within `phase_time_tolerance_s` (0.5 s) of it. A run that is
  right in order but off in time gets the new verdict `timing`. This lets a tester say
  not only what should be true but when the situation changes, which is the question the
  project asks of the labels.
- **Times are optional.** No existing expectation has one, so all results are unchanged
  (23 match, 3 partial). Times should come from testers, not be filled in from what the
  labels already do.
- **Phases can be added anywhere**: inserted before any phase, or added at the selected
  moment, where they take their place in time order. Before, a new phase could only be
  appended and then moved up one step at a time.
- The time of a phase can be typed, taken from the selected moment, or set by dragging its
  marker on the timeline.

## 2026-10-05: An automaton drives

Asked for by the user: can a DFA over the labels control the car on its own, and behave
well? Until now the automata only judged recordings.

**What was built**

- `semalpha/controllers.py`. A *controller* is an automaton plus one action per state.
  The action of the current state is what the car does; nothing else decides. Four
  actions: `go`, `hold_at_line`, `hold_inside`, `stop`. A fixed *executor* turns an action
  into a target speed from the geometry of the ego's own route. It knows nothing about
  traffic, signs or signals, so every such decision has to come from the labels.
- `semalpha/run.py` closes the loop: every 0.1 s the world is labelled, the automaton
  steps, the action becomes a speed. The state is recorded with each frame.
- `semalpha/drive.py` runs a controller on the 17 staged variants and on random traffic
  (2 to 6 cars on random routes; at the signal, a random point of the cycle), next to the
  simulator's own driver in the same traffic, and writes `docs/controller.md`.
- The inspector shows controller runs with the controller's live state diagram, and the
  random draws that failed.

**How a run is judged, and why not only by the rules.** A run passes when the ego arrives
and no rule automaton reports a violation. The controller and the rules read the same
labels, so that alone would be marking one's own homework. Each run is therefore also
measured from positions and speeds: collision, closest distance, time next to the
simulator's own driver, and a flag for "a car with right of way braked hard next to the
moving ego". The first version of that flag compared each car's braking with the reference
run and was wrong: it mostly caught cars braking for their own stop sign after the
reference ego had already left. The flag is still only a prompt to look: it also fires on a
car slowing for its own turn or red light.

**Three controllers**

| Controller | Idea | Staged (17) | Random traffic (40) |
|---|---|---|---|
| `dfa_v1` | hold at the line for a red or stoppable yellow, a car that outranks the ego and is too close, a blocked path or exit; otherwise go; keep checking until past the point of no return | 17 passed | 39 passed, 0 collisions |
| `dfa_v2` | as v1, but wait for three clear frames, then commit at the line and do not stop again | 17 passed | 36 passed, **2 collisions** |
| `dfa_v3` | as v1, reading the candidate label `priority_gap_safe`, and braking while crossing if a car that should give way no longer can | 17 passed | 40 passed, 0 collisions |

With cars ahead of the ego in its own lane, `dfa_v3` passed 38 of 40, with one collision.
Mean time in random traffic: 27.2 s (v1) and 26.6 s (v3), against 22.4 s for the
simulator's own driver, which knows where every car is going.

**What the runs showed about the labels.** All of the following came from random traffic.
The staged variants, on which the labels were developed, showed none of it.

1. *Two labels about "every car" do not combine into a fact about one car.*
   `!ego_has_priority !gap_safe` was meant as "a car that outranks the ego is too close".
   It is also true when one car outranks the ego from far away and another, which owes the
   ego priority, is close: the normal case on a roundabout. `dfa_v1` waited at the line for
   nobody, flipped between going and holding, and the rule `respect_right_of_way` reported
   violations that had not happened. Two of the three roundabout failures first blamed on
   `gap_safe` flickering were this. **Candidate label `priority_gap_safe`** says it in one
   fact. The rule now reads it (the 26 catalog verdicts are unchanged) and so does
   `dfa_v3`. The 19 reviewed labels are untouched. **Awaiting review.**
2. *A stationary car reads as a safe gap.* True for a parked car, false for a car with
   right of way that is waiting for its own gap or for green: it moves off together with
   the ego. `dfa_v2` committed on such a gap and collided twice. `dfa_v1` and `dfa_v3`
   start, see the gap close within half a second, and stop again.
3. *`gap_safe` assumes the ego turns at the lane's speed limit.* The simulated car turns at
   about two thirds of it, so a gap can read safe at the line and unsafe a second later.
4. *`others_can_yield` says "can still stop", not "is going to".* In three of the eight
   roundabout draws a car entering from the next arm did not give way to the ego on the
   ring. The first `dfa_v3`, already committed, did not react and was hit once. The state
   `avoid` now brakes once such a car can no longer stop; in those three draws the ego
   slowed from about 7 m/s to between 0.2 and 3.6 m/s and nobody was hit. The price: in
   four signal draws the ego lost about 1.5 m/s for an oncoming car that might have been
   turning across it and was in fact going straight. That is the cost of not knowing where
   others are going.
5. *Priority on red.* An ego that enters on a late yellow it could not stop for and is
   still inside when the light turns red is never credited with priority, so the rule
   reports a violation (one draw). This is open point 6 of the vocabulary, now seen.
6. *No label for a car ahead in the ego's lane.* The ego ran into the back of a car queued
   at a red light (one draw of 40 with cars ahead). Known, now measured.

**What the runs showed about the simulator**

- Background cars do not always give way to the ego where they should (finding 4). A
  likely reason, not checked: the ego is an outside vehicle to SUMO, which may not know
  where it is heading. `dfa_v1` has no answer to this. It was not hit in those draws,
  in which its needless waits made it arrive later.
- Told to stand still just before or inside a bend, the simulated car creeps at about
  0.1 m/s. In one `dfa_v1` draw it crept over the point of no return while waiting inside
  the roundabout entry, which is that controller's one remaining failure.
- `hold_at_line` used to roll on to the edge of shared road once the bumper was over the
  line. It now halts on the spot; only `hold_inside` moves up.

**Decisions**

- `dfa_v2` is kept as the example of a controller the tests reject.
- Runs made with `--set` (changed thresholds) are stored under `outputs/trials/` so they
  never replace the recorded ones.
- `docs/automata.md` covers the 26 catalog runs; controller runs are in
  `docs/controller.md`.

**Not done**

- No change to `gap_safe` for findings 2 and 3; they are listed as open points 8 and 9 in
  [vocabulary.md](vocabulary.md).
- No car-following label.
- Expected label sequences for controller runs: none written, so they show as "none".
- Eight draws per scenario is a small sample. The passes show that a hand-written DFA can
  drive these junctions; they do not show how often it would fail.

## 2026-10-05: `priority_gap_safe` accepted

The user accepted the candidate label under its name. It is now proposition 20 and is
listed with the others in [vocabulary.md](vocabulary.md) and the README. Nothing about its
definition changed, so no run or result changed.

- On the 26 catalog runs it is true 76% of the time (`gap_safe`: 74%) and differs from
  `gap_safe` only while the tight gap is to a car that owes the ego priority.
- `python -m semalpha.label --stats` now covers the catalog's runs only. With controller
  runs recorded next to them, the statistics had started to describe whatever a
  controller did, and the table in vocabulary.md could no longer be reproduced.
- Suggested next: a label for a car ahead in the ego's own lane, the one remaining cause
  of a collision, then the standing-car case of `gap_safe`. Not started.

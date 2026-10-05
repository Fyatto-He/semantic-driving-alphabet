# semantic-driving-alphabet

**Semantic alphabets for automata-guided driving.** A research prototype, built on the
[SMARTS](https://github.com/huawei-noah/SMARTS) driving simulator, for finding and testing
a small set of **semantic labels** that describe what
is going on at a road junction: `at_entry_line`, `stop_sign`, `ego_has_priority`,
`gap_safe`, and so on.

The labels are meant to become the alphabet of an automaton (DFA / reward machine) that
guides a driving policy. The alphabet describes the world; the automaton and the policy
decide what to do. This repository covers the first part: choosing the labels and
checking, frame by frame, that they change when a human driver's reasoning would change.
It also tests how far the labels carry: small automata judge recorded runs, and a
hand-written automaton can be put in charge of the car.

**Status (2026-10-05).** Four junction scenarios, 26 recorded runs, 20 labels, a set of
rule automata, and a frame-by-frame inspector work end to end. The label sequences agree with the hand-written expectations in 23 of 26 runs,
and one general set of eight small automata gives the expected verdict on all 26. A
hand-written automaton that reads only the labels drives all 17 staged variants and 40 of
40 draws of random traffic without a collision or a broken rule. It needed one new label
to get there, and it runs into a car queued ahead of it, which no label describes; see
[section 8](#8-controller-automata). No policy is trained.

To look at results without installing anything, open
[docs/inspector.html](docs/inspector.html) in a browser (a snapshot of the recorded runs).

## Contents

1. [How it works](#1-how-it-works)
2. [Requirements](#2-requirements)
3. [Setup, step by step](#3-setup-step-by-step)
4. [Running the pipeline](#4-running-the-pipeline)
5. [Looking at the results](#5-looking-at-the-results)
6. [The labels](#6-the-labels)
7. [The rule automata](#7-the-rule-automata)
8. [Controller automata](#8-controller-automata)
9. [Scenarios and drivers](#9-scenarios-and-drivers)
10. [Changing things](#10-changing-things)
11. [Project structure](#11-project-structure)
12. [Known limits](#12-known-limits)
13. [Further reading](#13-further-reading)

## 1. How it works

```
 maps + scenario catalog
          |
          v
 1. SIMULATE      SMARTS + SUMO drive each scenario once          -> outputs/runs/*.json
          |       (one raw snapshot of the world per 0.1 s)
          v
 2. LABEL         20 labeling functions run on every snapshot     -> outputs/traces/*.txt
          |       and the result is compared with the expected
          |       label sequence written by hand for that run
          v
 3. VERIFY        small rule automata read each label sequence    -> a verdict per run
          |       and say whether the run succeeded and which
          |       rules it broke
          v
 4. INSPECT       one web page to step through any run            -> outputs/inspector.html

 5. DRIVE         (optional) an automaton reads the labels live   -> docs/controller.md
                  and drives the ego; its runs go through 2 to 4
```

Three ideas hold it together:

- **Simulate once, label many times.** Step 1 really runs the simulator: the cars are
  driven live by SUMO's driver model or by a script, and every frame is recorded. Steps 2
  to 4 only read those recordings. Changing a label or a threshold therefore takes
  seconds, not a new simulation. The scenarios are staged (fixed routes, fixed departure
  times, no randomness), so a re-simulation reproduces the same run.
- **A label is a fact about one frame.** Each labeling function looks at a single snapshot
  (where every car is, how fast, which way it faces, what the signals show) plus the
  static map, and answers true or false. It has no memory of earlier frames. Anything that
  needs memory, such as "I already stopped at the line", is left to the automaton.
- **Expectations come first.** For every run there is a hand-written sequence of phases
  ("held at the stop line", "free to go", "crossing"), each listing which labels must be
  on or off. They were written before the labeling code, so comparing the two is a test of
  the labels and not a description of them. Expectations are edited in the inspector page
  itself (section 5), not in code.

Step 5 is the exception to "simulate once": there the labels are computed while the
simulator runs, because the car's next move depends on them.

Nothing here learns. There is no reinforcement learning and no trained policy yet.

## 2. Requirements

| Need | Notes |
|---|---|
| Windows 10 or 11, 64-bit | Developed and tested on Windows 11. Linux should work and needs no patch, but is untested here. |
| Python 3.10, 64-bit | SMARTS 2.0.1 supports Python 3.8 to 3.11. Check with `py -3.10 --version`. Install from python.org if missing. |
| Microsoft C++ Build Tools | One dependency (pybullet) has no ready-made Windows package and is compiled during install. Get "Build Tools for Visual Studio" from visualstudio.microsoft.com and select the workload **Desktop development with C++**. |
| Git | To clone the repository. |
| About 3 GB of free disk space | Mostly the Python environment. |

No GPU is needed.

## 3. Setup, step by step

All commands are run in a terminal (PowerShell or Command Prompt) opened in the project
folder.

**Step 1. Get the code.**

    git clone https://github.com/Fyatto-He/semantic-driving-alphabet.git
    cd semantic-driving-alphabet

**Step 2. Create a Python environment inside the project.**

    py -3.10 -m venv .venv

This creates the folder `.venv`. Every later command uses `.venv\Scripts\python`, so
nothing needs to be "activated".

**Step 3. Install the packages.**

    .venv\Scripts\python -m pip install --upgrade pip
    .venv\Scripts\python -m pip install -r requirements.txt

This takes about 10 minutes. Most of that is the line
`Building wheel for pybullet ... still running`, which is the compile step; it prints
nothing for several minutes. It ends with `Successfully installed ... smarts-2.0.1 ...`.

`requirements.txt` names the two top-level packages (SMARTS with its SUMO, Envision and
Gymnasium extras, and matplotlib). `requirements.lock.txt` lists the exact versions of
everything that was installed when this was last tested. To reproduce that environment
exactly, install from the lock file instead.

**Step 4. Patch SMARTS for Windows.**

    .venv\Scripts\python scripts\patch_smarts_windows.py

Expected output:

    patched:         core/utils/core_logging.py
    patched:         core/utils/resources.py

SMARTS officially supports only Linux and macOS. This script replaces two small
Unix-only snippets inside the installed SMARTS package. It is safe to run twice (it then
prints `already patched`), and must be run again after SMARTS is reinstalled. Skip this
step on Linux.

**Step 5. Check that the simulator works.**

    .venv\Scripts\python -m semalpha.run t_stop_left clear

This builds one map, simulates one small scenario with two different drivers (about 20
seconds), and should print two lines like:

    t_stop_left     clear                 sumo              t=0.1-18.6s | enters 10.1s, clear 13.6s | stops: 9.8-9.9s (0.1 m before line) | closest: none
    t_stop_left     clear                 roll_through      t=0.2-20.9s | enters 9.7s, clear 12.6s | stops: none | closest: none | events: ['reached_goal']

Lines saying `Success.` and a `UserWarning` about `moveToXY` are normal.

### If something goes wrong

| Symptom | Cause and fix |
|---|---|
| `error: Microsoft Visual C++ 14.0 or greater is required` during install | The C++ Build Tools are missing. Install them (section 2) and repeat step 3. |
| Install errors, and `.venv\Scripts\python --version` does not say 3.10 | The environment was made with another Python. Delete `.venv` and repeat from step 2. |
| `TypeError: argument of type 'NoneType' is not iterable`, with `ctypes.CDLL(None)` in the traceback | Step 4 was skipped. Run the patch script. |
| `PermissionError ... smarts\assets\vehicles\tmp....py` | Same: run the patch script. |
| The patch script prints `NOT APPLIED (source differs from SMARTS 2.0.1)` | A different SMARTS version is installed. Install the version in `requirements.txt`. |
| `FileNotFoundError ... outputs\runs\...json` | That run has not been simulated yet. Run pipeline step 1. |

## 4. Running the pipeline

### Step 1: simulate and record (about 5 minutes)

    .venv\Scripts\python -m semalpha.run

Compiles the maps, then simulates every scenario variant with every driver: 26 runs. Each
run is saved as `outputs/runs/<scenario>/<variant>__<driver>.json` and summarised in one
line of raw facts (when the ego enters and clears the junction, when it is stationary,
how close it comes to another car, the signal sequence, simulator events). These lines
contain no labels; they are for checking that a scenario stages what it claims.

Repeat this step only after changing a map, a scenario or a driver. To simulate less:

    .venv\Scripts\python -m semalpha.run t_stop_left                      # one scenario
    .venv\Scripts\python -m semalpha.run t_stop_left wait_for_gap         # one variant, all its drivers
    .venv\Scripts\python -m semalpha.run t_stop_left wait_for_gap sumo    # one run

### Step 2: label and compare (a few seconds)

    .venv\Scripts\python -m semalpha.label

Computes all 20 labels for every frame of every recorded run, writes each label sequence
to `outputs/traces/<scenario>/<variant>__<driver>.txt`, and prints one verdict per run:

    match    t_stop_left     wait_for_gap          sumo                milestones 6/6
    match*   signal_straight yellow_far            sumo                milestones 8/8, unexplained 2.0s
    ...
    23 match, 3 match*

| Verdict | Meaning |
|---|---|
| `match` | Every expected phase was reached in order, every frame fits the current or next phase, and no forbidden combination occurred. |
| `match*` | Every expected phase was reached, but for some stretch the labels fit neither the current nor the next phase. Worth a look. |
| `timing` | Every expected phase was reached in order, but one that was given a start time is reached more than 0.5 s earlier or later than that. |
| `none` | Nothing has been written for this run yet. |
| `MISMATCH` | An expected phase was never reached, or a combination listed as "never" occurred. |

Useful variations:

    .venv\Scripts\python -m semalpha.label t_stop_left wait_for_gap sumo   # print expected phases and the label sequence
    .venv\Scripts\python -m semalpha.label --trace                         # print them for every run
    .venv\Scripts\python -m semalpha.label --stats                         # per label: share of time true, changes, flickers
    .venv\Scripts\python -m semalpha.label --set gap_margin_s=3            # try a threshold without editing any file

### Step 3: judge the runs with the rule automata (a few seconds)

    .venv\Scripts\python -m semalpha.verify

Feeds every label sequence to the automata in `semalpha/rules.py` and prints a verdict per
run, compared with the verdict written down beforehand:

    ok   t_stop_left     clear                 roll_through         completed | rules broken: stop_at_stop_sign at 9.7s | halted: nowhere | idle while free: 0.0s
    ...
    26 of 26 verdicts as expected

`ok` means the verdict is the expected one; `DIFF` prints what was expected instead.

    .venv\Scripts\python -m semalpha.verify t_stop_left wait_for_gap   # also show every automaton's state changes
    .venv\Scripts\python -m semalpha.verify --set gap_margin_s=1       # judge with a different label threshold
    .venv\Scripts\python -m semalpha.verify --docs                     # regenerate docs/automata.md

### Step 4: open the inspector

To look at the runs **and edit what is expected of them**, start the inspector with saving
switched on. It opens in your browser:

    .venv\Scripts\python -m semalpha.serve

The first page takes a few seconds while the runs are labelled. Leave the terminal open
while you work and stop it with Ctrl+C. The server listens on this computer only.

To just look, or to hand the page to someone who has not installed anything, build it as
a single file instead:

    .venv\Scripts\python -m semalpha.inspector

That writes `outputs/inspector.html`. Open it by double-clicking it. Everything works in
the file version too, except that edited expectations are offered as a download instead of
being saved into the project.

To refresh the snapshot that is kept in the repository:

    .venv\Scripts\python -m semalpha.inspector docs\inspector.html

### Step 5 (optional): let an automaton drive (about 10 minutes)

    .venv\Scripts\python -m semalpha.drive dfa_v3

Puts the controller automaton `dfa_v3` (section 8) in charge of the ego on every staged
variant, records the runs next to the others, and prints one line per run:

    PASS roundabout      yield_to_circulating   reached the destination | rules broken: none | halted: at_line | took 26.1s (reference 24.3s) | closest 7.8 m
    ...
    dfa_v3 on the staged variants: 17 of 17 passed (reached the destination, no rule broken); 0 collisions; 0 flagged for cutting another car off

"Reference" is the time SUMO's own driver took in the same traffic. Eight random draws
per scenario take about as long again.

    .venv\Scripts\python -m semalpha.drive dfa_v3 roundabout              # one scenario
    .venv\Scripts\python -m semalpha.drive dfa_v3 --random 8              # 8 draws of random traffic per scenario
    .venv\Scripts\python -m semalpha.drive dfa_v3 --random 8 --with-leaders   # ... some with a car ahead in the ego's lane
    .venv\Scripts\python -m semalpha.drive dfa_v3 --judge                 # no simulation: judge the runs already recorded
    .venv\Scripts\python -m semalpha.drive dfa_v3 --set gap_margin_s=3    # drive with a different label threshold
    .venv\Scripts\python -m semalpha.drive --judge --docs                 # regenerate docs/controller.md

Random draws are reproducible: draw 3 of a scenario is the same traffic every time. Runs
made with `--set` are kept under `outputs/trials/` and never replace the recorded ones.
After driving, run steps 2 to 4 again to see the new runs in the inspector. Controller
runs appear there with the controller's own state diagram, and so do the random draws that
failed.

### Optional: figures

    .venv\Scripts\python -m semalpha.plot

Writes `docs/figures/scenarios.png` (the maps and routes) and `docs/figures/traces.png`
(label timelines of six representative runs).

## 5. Looking at the results

### The inspector

- **Dropdown at the top**: choose a run. `✓` matches the expectation, `≈` matches with an
  unexplained stretch, `✗` differs.
- **Map**: the junction from above. The ego is blue, other cars orange, the entry line is
  the short dark bar across the ego's lane, the dashed line is the ego's route.
- **Left / Right arrow**: one frame back or forward. **Shift + arrow**: jump to the
  previous or next frame where any label changes. **Space**: play or pause.
- **Now**: the ego's speed and its distance to the entry line.
- **Labels**: all 19, the ones that are on shown in bold.
- **Cars whose path may meet the ego's**: for each such car and each way it might be
  going, its distance from the ego's path, its speed, who outranks whom, and whether the
  gap is sufficient. This is the reasoning behind `conflict_present`, `ego_has_priority`
  and `gap_safe` at that moment.
- **Expected for this run**: the phases written for this run and when each was reached,
  plus the verdict expected from the automata. Click **Edit** to change them (below).
- **Automata: live state diagram**: a row of buttons, one per automaton, each showing the
  state that automaton is in at this moment (a broken rule in red). Click one to draw it as
  a graph that updates as you step through the run:
  - the current state is filled in; states already visited have a bold outline;
  - the transition just taken is blue, earlier ones are bold, ones never taken are faint;
  - on the ways out of the current state, each condition is bold if it holds right now;
  - beside the graph: the rule in words, the path so far (click a step to jump to that
    moment), and for each way out which conditions are met and which are missing.
- **Timeline at the bottom**: one row per label, a bar wherever it is on. Numbered lines
  mark the expected phases; shaded bands are unexplained stretches. Below the labels, one
  band per automaton shows its state over time. Click or drag to jump.

### Editing what a run is expected to show

Start `python -m semalpha.serve`, pick a run, and click **Edit** in the "Expected for this
run" card. The map stays in view while you edit, and every change is re-checked against
the recorded run immediately: the header, the timeline and the run's mark in the dropdown
all update as you go.

- **A phase** is one stretch of the run, described in words, with the labels that must be
  ON or OFF during it. Labels you leave out may be anything.
  - Type the description in the box.
  - **+ label...** adds a label. It starts with the value it has at the selected moment, so
    first move the time slider to the moment the phase should describe.
  - Click a label to flip it between ON and OFF; click its `x` to remove it.
  - The `+` button inserts a new phase before this one, the arrows move the phase earlier
    or later, and the cross deletes it.
  - **may be skipped** marks an in-between phase that a run need not pass through.
  - You see whether the phase fits the moment you have selected.
- **When a phase begins.** A phase may be given the time at which you expect it to begin.
  The check then also says whether the labels reach the phase at that time, allowing
  0.5 s either way (`phase_time_tolerance_s` in `thresholds.yaml`). Three ways to set it:
  - type the seconds into **begins at**;
  - click **use ... s** to take the selected moment;
  - drag the phase's marker (a small triangle on the timeline's axis). The replay follows
    the marker while you drag, so you can see the moment you are choosing.

  Next to it you see when the labels actually reach the phase, and how far off that is.
  Click that time to jump there. **clear** removes the expected time again. A phase that
  is given a time moves to its place in the order by itself.
- **+ Add a phase at ... s** adds a phase that begins at the selected moment, in the right
  place in the order. **+ Add a phase at the end** appends one without a time. Phases are
  checked in the order listed.
- **Must never happen** lists label combinations that must not occur at any moment.
- **Expected verdict of the automata**: whether the ego reaches its destination, which
  rules it breaks, and where it comes to a halt. The line below tells you whether that is
  what the automata actually found.

Taking changes back:

| Button | What it does |
|---|---|
| **Undo** (Ctrl+Z) | Takes back the last change. Press again to go further back. Typing in one box, or one drag, counts as a single step. |
| **Redo** (Ctrl+Y) | Puts back what Undo just took away. |
| **Revert this run** | Puts the selected run back to how it was last saved. Other runs keep their edits. |
| **Discard all changes** | Puts every run back to how it was last saved. |

Revert and Discard can themselves be undone.

**Save** appears as soon as something differs from the saved file, with a count of the
runs you have edited. It writes `semalpha/expectations.json`; from then on
`semalpha.label` and `semalpha.verify` use the new expectations. Unsaved edits survive a
reload of the page. In the single-file version of the inspector the button reads
**Download expectations.json**: put the downloaded file at `semalpha/expectations.json`
to keep the changes.

A tester who should not be influenced by the current labels can ignore the timeline and
write phases from the map alone; there is no mode yet that hides the labels.

### A label sequence as text

`.venv\Scripts\python -m semalpha.label t_stop_left wait_for_gap sumo` prints the full
set of labels at the start and then only what changes:

      0.1-  2.8s  ego_has_priority gap_safe others_can_yield exit_clear can_stop_before_entry
      2.9-  6.0s  +approaching_junction +stop_sign
      6.1-  7.4s  +conflict_present -ego_has_priority
      ...
      9.8- 12.7s  +ego_stopped
     14.9- 15.0s  +gap_safe
     15.3- 16.7s  +in_junction +in_waiting_area +ego_has_priority -at_entry_line -conflict_present ...

`+name` means the label turned on at the start of that stretch, `-name` that it turned off.

### Watching a simulation live (optional)

SMARTS ships its own 3D viewer, Envision. Start it in one terminal, open
http://localhost:8081 in a browser, and add `--envision` to a run command in a second
terminal:

    .venv\Scripts\scl envision start
    .venv\Scripts\python -m semalpha.run t_stop_left wait_for_gap sumo --envision

Envision shows the cars but not the labels.

## 6. The labels

Each label is one short function in `semalpha/predicates.py`. For every frame the labeler
builds a `View` of that frame (`semalpha/relations.py`) and calls all 20 functions on it.

| Group | Label | True when |
|---|---|---|
| Progress | `approaching_junction` | the junction's entry line is within 50 m ahead and not yet reached |
| | `at_entry_line` | the ego's front bumper is within 2 m before the stop / yield / signal line |
| | `in_junction` | the ego's front is past the entry line and its rear has not left the junction |
| | `in_waiting_area` | the ego is inside but not yet on road shared with any movement that may currently move |
| Control | `stop_sign` | the ego's movement through this junction is stop-controlled |
| | `signal_go`, `signal_caution`, `signal_stop` | the signal aspect facing the ego |
| Interaction | `conflict_present` | some car's possible path meets the ego's remaining path, and neither has passed that place |
| | `ego_has_priority` | the rules give the ego right of way over every such car |
| | `gap_safe` | going now, the ego and every such car would use the shared road at least 2 s apart |
| | `priority_gap_safe` | the same, but only for the cars that outrank the ego |
| | `others_can_yield` | every car that owes the ego priority can still stop short of the ego's path |
| Occupancy | `path_blocked` | a car is physically on the ego's path inside the junction |
| | `exit_clear` | there is room beyond the junction for the ego to leave it completely |
| Ego motion | `ego_stopped` | the ego's speed is below 0.1 m/s |
| | `can_stop_before_entry` | braking at 3 m/s², the ego can still halt before the entry line |
| Terminal | `collision`, `off_road`, `goal_reached` | simulator event, or the geometric equivalent |

`priority_gap_safe` was added after an automaton first drove (section 8). It exists
because `ego_has_priority` and `gap_safe` each speak about every car at once: "no priority
and gap not safe" is also true when one car outranks the ego from far away and a different
car is close. `priority_gap_safe` keeps both facts about the same car.

Three rules shape them:

- A label states a fact, never a decision. There is no `should_go` or `must_yield`.
- Other cars are judged only from what is visible: position, heading, speed, size. Their
  routes are unknown, so a car that could still go several ways is treated as possibly
  going any of them. A car approaching from the left counts as a possible conflict until
  it visibly turns off.
- Every number (50 m, 2 m, 2 s, 3 m/s², ...) is in `semalpha/thresholds.yaml`.

The code is layered so that the labels themselves stay short:

| Layer | File | Contains |
|---|---|---|
| 1. Helpers | `helpers.py`, `mapinfo.py` | distances, travel times, vehicle outlines, lane geometry, the map's right-of-way table |
| 2. Relations | `relations.py` | facts about the ego and one junction or one other car, e.g. "this car's possible path meets mine", "I outrank it", "the gap to it is safe" |
| 3. Labels | `predicates.py` | the 20 true/false facts, mostly one line each, built from layer 2 |

Example: `gap_safe` is `all(v.gap_safe(c) for c in v.conflicts)`. Layer 2 finds the
conflicts (which cars, which of their possible paths, where the paths meet) and judges
each gap; layer 1 supplies the distances and travel times.

Definitions, evidence from the runs, and open questions are in
[docs/vocabulary.md](docs/vocabulary.md).

## 7. The rule automata

An automaton here is a small state machine that reads the labels one frame at a time. It
is in exactly one state, and each frame it either stays or moves, depending on which
labels are on. Unlike a label, it remembers: that is where "I already stopped at the line"
or "I was outside when the light turned red" is kept.

There is **one rule set for every scenario** (`semalpha/rules.py`), made of eight small
automata. None of them mentions a junction type.

| Automaton | Kind | What it tracks |
|---|---|---|
| `reach_goal` | task | progress: approach, at_line, inside, cleared, done. Ending in `done` is success. |
| `stop_at_stop_sign` | rule | where a stop sign applies, halt at the line before entering |
| `obey_red_signal` | rule | do not enter on red; being inside when it turns red is allowed |
| `stop_on_yellow_when_able` | rule | do not enter on a yellow that left room to stop |
| `respect_right_of_way` | rule | do not pass the point of no return while a car that outranks the ego is too close |
| `no_collision` | rule | never touch another car |
| `stay_on_road` | rule | never leave the road |
| `where_it_waited` | branch | where the ego came to a halt: nowhere, at the line, inside, both |

A rule automaton that reaches `violated` stays there, and the time it got there is
reported. The verdict of a run is: did `reach_goal` end in `done`, which rules were broken
and when, and where the ego waited. One extra number, "idle while free", measures how long
the ego stood still although nothing held it; it separates a hesitant run from a normal
one.

State diagrams, the full verdict table, and what the result does and does not show are in
[docs/automata.md](docs/automata.md).

## 8. Controller automata

The rule automata watch. A **controller automaton** is in charge: it reads the same labels
live, each of its states carries an action, and the action of the state it is in is what
the car does. Nothing else decides. This tests whether the labels are enough to drive on,
not only to judge with.

| Action | The car |
|---|---|
| `go` | follows its route at cruising speed, slowing for the turn |
| `hold_at_line` | comes to a halt at the junction's entry line |
| `hold_inside` | already inside: halts short of any road it shares with others |
| `stop` | brakes to a halt where it is |

Turning an action into a speed is done by a fixed piece of code, the executor
(`semalpha/controllers.py`). It knows the shape of the ego's own route and nothing about
traffic, signs or signals, so every such decision has to come from the labels.

Three controllers are included (`semalpha/controllers.py`):

| Controller | Idea | Staged variants (17) | Random traffic (40 draws) |
|---|---|---|---|
| `dfa_v1` | hold at the line for a red or stoppable yellow, for a car that outranks the ego and is too close, for a blocked path or exit; otherwise go; keep checking until past the point of no return | 17 pass | 39 pass, no collision |
| `dfa_v2` | as `dfa_v1`, but wait for three clear frames, then commit at the line | 17 pass | 36 pass, **2 collisions** |
| `dfa_v3` | as `dfa_v1`, reading `priority_gap_safe`, and braking while crossing if a car that should give way no longer can | 17 pass | 40 pass, no collision |

**How a run is judged.** It *passes* when the ego reaches its destination and no rule
automaton reports a violation. The controller and the rules read the same labels, so each
run is also measured from positions and speeds alone: was there a collision, how close did
the ego come to another car, how long did it take next to SUMO's own driver in the same
traffic, and did a car with right of way brake hard next to the moving ego.

**What it shows so far**

- A hand-written DFA of seven states over these labels gets through every staged variant
  and all 40 random draws, at a stop sign, a signal, an unprotected left turn and a
  roundabout, with the same automaton everywhere.
- It is slower than SUMO's driver (26.6 s against 22.4 s on average in random traffic),
  because it cannot see where other cars are going and waits for everything that might
  cross its path.
- The staged variants did not find a single problem. Random traffic found six gaps in the
  labels and two quirks of the simulator: see [docs/design_log.md](docs/design_log.md).
  The largest gap led to a new label, `priority_gap_safe`.
- With a car ahead in the ego's own lane, `dfa_v3` passes 38 of 40 draws and once runs
  into the back of a car queued at a red light. No label describes a car ahead.
- A controller can fail the tests: `dfa_v2` looked like an improvement and collided twice.

**What it does not show.** Eight draws per scenario is a small sample; passing them says a
DFA *can* drive these junctions, not how often it would fail. Background cars mostly brake
for the ego, which hides mistakes. And passing the rule automata is not independent
evidence, for the reason above.

Diagrams and every result table are in [docs/controller.md](docs/controller.md). To write
your own controller, see section 10.

## 9. Scenarios and drivers

![maps and routes](docs/figures/scenarios.png)

| Scenario | Map | What the ego does | Variants |
|---|---|---|---|
| `t_stop_left` | `t_stop` | left turn out of a side road with a STOP sign | clear, wait_for_gap, gap_closes, other_turns_off |
| `t_major_left` | `t_stop` | left turn from the main road across oncoming traffic | clear, oncoming_then_gap, minor_car_waiting, oncoming_turns_right |
| `signal_straight` | `cross_signal` | straight through a signalized four-way junction | green, red_then_green, yellow_far, yellow_near |
| `signal_left` | `cross_signal` | left turn on a permissive green | oncoming_then_gap |
| `roundabout` | `roundabout` | enter a single-lane roundabout, leave at the second exit | empty, yield_to_circulating, circulating_exits, entering_car_yields |

A *variant* stages one decision branch with a few background cars, each with a fixed route
and departure time. Every variant is driven by:

- **`sumo`**: SUMO's own driver model drives the ego. It obeys signs, signals and right of
  way, so it serves as the rule-following reference. Note that it knows every other car's
  route, which the labels do not.
- **scripted drivers** (only where listed): the ego follows a fixed speed script and
  ignores traffic. These stage what a rule-follower never does: rolling through a stop
  sign, pulling out too early, running a red light, waiting needlessly.
- **controller automata** (after pipeline step 5): `dfa_v1`, `dfa_v2`, `dfa_v3` decide
  from the labels alone (section 8).

The step-by-step description of what a human driver notices in each variant is in
[docs/traces.md](docs/traces.md).

## 10. Changing things

After any change below, run pipeline steps 2 to 4 again. Step 1 is needed only where
noted. To change what a run is expected to show, see "Editing what a run is expected to
show" in section 5.

### Change a threshold

Edit the value in `semalpha/thresholds.yaml`. To try a value first without editing:

    .venv\Scripts\python -m semalpha.label --set comfortable_decel=4.5

### Add or remove a label

Add a function to `semalpha/predicates.py`:

```python
@proposition("ego motion")
def ego_fast(v: View) -> bool:
    """The ego is driving faster than the 'fast' threshold."""
    return v.ego.speed > v.th.fast_speed
```

and its number to `semalpha/thresholds.yaml` (`fast_speed: 10.0`). The label then appears
in every trace, in the statistics and in the inspector. To remove a label, delete its
function; if an expectation mentions it, remove it there too (in the inspector). The
inspector supports at most 31 labels.

### Add or change a rule automaton

Edit `semalpha/rules.py`. An automaton is a name, an initial state, and for each state an
ordered list of `(condition, next state)`; the first condition that holds is taken, and
with none the automaton stays. A condition lists labels that must be on (`name`) or off
(`!name`):

```python
dont_block_the_exit = Automaton(
    name="dont_block_the_exit",
    rule="Do not enter the junction unless there is room to leave it.",
    initial="outside",
    transitions={
        "outside": (("in_junction !exit_clear", "violated"), ("in_junction", "inside")),
        "inside": (("!in_junction", "outside"),),
    },
    bad=("violated",),
)
```

Add it to the `AUTOMATA` list. If it changes what a run should be judged as, update the
expected verdict of that run in the inspector (section 5).

### Write a controller automaton (needs step 5 for its runs)

Add a `Controller` to `semalpha/controllers.py`: an automaton written exactly like a rule
automaton, plus one action for every state. This one stops at every junction and goes
when nothing that outranks it is close:

```python
cautious = Controller(
    name="cautious",
    idea="Halt at every entry line, then go when no car that outranks me is close.",
    automaton=Automaton(
        name="cautious",
        kind="controller",
        rule="Drives the ego: the action of the current state is what the car does.",
        initial="drive",
        transitions={
            "drive": (("approaching_junction", "halt"), ("at_entry_line", "halt")),
            "halt": (("at_entry_line ego_stopped", "look"), ("in_junction", "move")),
            "look": (("signal_stop", "look"), ("!priority_gap_safe", "look"), ("", "move")),
            # moving off: back to looking if things change before the point of no return
            "move": (("in_junction !in_waiting_area", "cross"),
                     ("signal_stop !in_junction", "look"),
                     ("!priority_gap_safe", "look")),
            "cross": (("!in_junction", "drive"),),
        },
    ),
    actions={"drive": GO, "halt": HOLD_AT_LINE, "look": HOLD_AT_LINE, "move": GO, "cross": GO},
)
```

Add it to the `CONTROLLERS` line at the bottom of the file, then:

    .venv\Scripts\python -m semalpha.drive cautious
    .venv\Scripts\python -m semalpha.drive cautious --random 8

The actions are `GO`, `HOLD_AT_LINE`, `HOLD_INSIDE` and `STOP`. A controller cannot set a
speed or read a distance; if it needs to know something, that something has to be a label.

### Add a scenario variant (needs step 1 for the new runs)

1. Add a `Variant` to a scenario in `semalpha/scenarios.py`:

   ```python
   Variant(
       "late_car",
       "A third car arrives after the ego has started to move.",
       cars=(Car("east_1", ("WJ", "JE"), depart=6), Car("east_2", ("WJ", "JE"), depart=12)),
       scripts={"hesitant": Script("Waits five seconds longer than needed.",
                                   holds=(Hold("entry", until=20.0),))},
   ),
   ```

   A `Car` is given by its route (edge names, first to last) and departure time. A
   `Script` is a cruising speed plus optional `Hold`s: stop at the entry line or the
   in-junction waiting point until a given time.
2. Simulate it: `.venv\Scripts\python -m semalpha.run <scenario> late_car`, and check the
   printed raw facts to see that the staging does what you intended.
3. Open the inspector (`python -m semalpha.serve`), select the new runs, and write what
   each is expected to show. Until you do, a run is listed as having no expectation.

### Add a map (needs step 1)

Create `semalpha/maps/<name>/` with `map.nod.xml` (junction positions and types),
`map.edg.xml` (roads between them) and `map.netccfg` (options for SUMO's `netconvert`).
The three existing maps are short examples. Print what SUMO made of it, including who
gives way to whom, with:

    .venv\Scripts\python -m semalpha.mapinfo <name>

## 11. Project structure

```
semalpha/                  the Python package (short for "semantic alphabet")
  maps/<name>/             map sources: nodes, edges, netconvert options
  scenarios.py             catalog: scenarios, variants, staged cars, scripted drivers
  drivers.py               the scripted speed-only ego driver
  build.py                 compiles maps and writes SMARTS scenario folders
  run.py                   step 1: simulate, record, print raw facts
  record.py                the recording format: one world snapshot per step
  mapinfo.py               reads a map: movements, signs and signals, right of way, routes
  helpers.py               layer 1: geometry and kinematics helpers
  relations.py             layer 2: relational facts for one frame
  predicates.py            layer 3: the 20 labels
  thresholds.yaml          every tunable number
  expectations.json        what every run is expected to show (edited in the inspector)
  expected.py              loads and checks expectations.json
  label.py                 step 2: label, compare, statistics
  automata.py              what an automaton is and how it reads labels
  rules.py                 the rule set: eight small automata
  verify.py                step 3: run the automata, compare verdicts
  controllers.py           controller automata and the executor that turns an action into a speed
  drive.py                 step 5: let a controller drive, on staged variants and random traffic
  inspector.py             step 4: builds the inspector page
  inspector.html           the inspector's page template
  serve.py                 step 4: serves the inspector so edits can be saved
  plot.py                  figures
docs/
  traces.md                what a human driver notices in each scenario
  vocabulary.md            the labels: definitions, evidence, open points
  automata.md              the rule automata: diagrams, verdicts, limits (generated)
  controller.md            the controller automata: diagrams, every result table (generated)
  design_log.md            decisions and the reasons for them
  inspector.html           snapshot of the inspector for the recorded runs
  figures/                 scenarios.png, traces.png
scripts/
  patch_smarts_windows.py  makes SMARTS 2.0.1 run on Windows
  probe_smarts.py          prints everything SMARTS exposes for one small junction
scenarios/probe_t_stop/    the small junction used by probe_smarts.py
requirements.txt           what to install
requirements.lock.txt      exact versions last tested
```

Created when you run things, and not stored in the repository:

```
.venv/                     the Python environment
build/                     compiled maps and SMARTS scenario folders
outputs/runs/              recorded runs
outputs/random/            random-traffic draws driven by a controller, and their summaries
outputs/trials/            runs made with changed thresholds (--set)
outputs/traces/            label sequences
outputs/inspector.html     the inspector page
```

## 12. Known limits

- **Perfect perception.** The labels see every car's exact position and speed, with no
  noise, no blind spots and no range limit. They do not see where a car is going.
- **Not validated by a learned policy.** The labels and rule automata have been checked
  against hand-written expectations on 26 staged runs. A hand-written automaton drives
  with them (section 8); nothing learned does.
- **Known gaps in the labels**, found by letting an automaton drive: a car standing still
  reads as a safe gap even when it is about to move off; `gap_safe` assumes the ego turns
  faster than it does; `others_can_yield` says a car can stop, not that it will; an ego
  that entered lawfully and is caught inside by a red light is never credited with
  priority. See the open points in [docs/vocabulary.md](docs/vocabulary.md).
- **Two rules are half-tested.** No run breaks `stop_on_yellow_when_able` or
  `stay_on_road`, so only their "no false alarm" side has been checked.
- **Three labels are untested.** `others_can_yield`, `exit_clear` and `off_road` never
  change value in any run so far.
- **One lane per direction.** Lane changes, queues and a car ahead in the ego's lane are
  not modelled.
- **Right of way follows SUMO's rules** (right-hand traffic).
- **The simulator does not police the ego.** SMARTS raises no event for running a stop
  sign or a red light; such violations show up only in the labels.
- **Background cars are mostly cooperative.** SUMO cars brake for a misbehaving ego, which
  softens the staged unsafe runs. They do not always give way to an ego that is driven by
  a script or a controller, even where they should.
- **Holding still is not exact.** Told to stand still just before or inside a bend, the
  simulated car creeps forward at about 0.1 m/s.
- **Windows support is unofficial.** Two patches were enough for everything used here.
- **Private SMARTS and SUMO internals** are read in a few places (`mapinfo.py`,
  `run.py`), so a different SMARTS version may need adjustments.

## 13. Further reading

- [docs/traces.md](docs/traces.md): the human reasoning each scenario is meant to capture.
- [docs/vocabulary.md](docs/vocabulary.md): label definitions, statistics, threshold
  sensitivity, concepts left out and why, open points.
- [docs/automata.md](docs/automata.md): state diagrams of the rule automata and their
  verdict on every run.
- [docs/controller.md](docs/controller.md): state diagrams of the controller automata and
  every result table, staged and random.
- [docs/design_log.md](docs/design_log.md): what was decided, what went wrong on the first
  comparison, and what was changed.

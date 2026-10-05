# Phase 2: decision-relevant observation traces

For each first-wave scenario: what a human driver notices, in order, and how each
observation changes what they do at a high level (keep going / hold / go / done).
Written before choosing any labels. Each branch is staged as a catalog variant
(`semalpha/scenarios.py`) and has been run: 17 variants, 26 runs. The raw timings are in
`outputs/runs/summary.txt`.

![scenario maps](figures/scenarios.png)

Two drivers produce the runs:

- **sumo**: SUMO's own driver model. It follows signs, signals and right of way, so it
  is the rule-following reference. It knows every other car's true route, which a human
  does not.
- **scripted**: an open-loop speed script that ignores traffic. Used for the branches a
  rule-follower never produces (violations, unsafe entries, needless waiting).

## A. `t_stop_left`: left turn out of a stop-controlled side road

| # | What the driver notices | What they do |
|---|---|---|
| 1 | There is a junction ahead on my route. | Keep going, get ready to slow. |
| 2 | My approach has a STOP sign. | Plan to stop at the line whatever the traffic. |
| 3 | I am at the line and have come to a halt. | The stop is done; from here only traffic matters. |
| 4 | A car from the left will cross my path, a car from the right is in the lane I am joining, and they outrank me. At least one would arrive before I am clear. | Hold. |
| 5 | The car from the left has passed the place where our paths cross. The one from the right has not. | Still hold. |
| 6 | Everyone who outranks me has passed, or is far enough away. | Go. |
| 7 | I am inside the junction, nothing is in my way, the lane I am entering has room. | Keep going. |
| 8 | I am fully out of the junction on the main road. | Turn complete. |

Branches:

| Variant / driver | What differs | Behaviour |
|---|---|---|
| `clear` / sumo | Step 4 never happens. | Stop, then go at once. The stop is still required. |
| `clear` / roll_through | Step 3 never happens. | Enters without stopping. Nothing is hit, but a rule is broken. |
| `wait_for_gap` / sumo | The nominal trace. | Stopped 9.8–15.1 s, then turns. |
| `wait_for_gap` / enter_too_early | Leaves at step 5. | Pulls out as the car from the right arrives; they pass within 7 m. |
| `wait_for_gap` / overcautious | Stays at step 6 for 11 s. | The world says "free to go" while the ego sits still. |
| `gap_closes` / sumo | After step 5 a second car appears from the left; the opening is about 4 s. | Keeps holding until all three have passed. |
| `other_turns_off` / sumo | The car from the left is actually turning into my road. | Goes at once, because SUMO knows the other car's route. |
| `other_turns_off` / wait_until_it_turns | Same world, human knowledge: the car *might* cross my path until it visibly turns. | Holds until the other car is in its turn, then goes. |

## B. `t_major_left`: unprotected left turn from the main road

| # | What the driver notices | What they do |
|---|---|---|
| 1 | Junction ahead where I turn left. | Keep going. |
| 2 | No sign or signal faces me. Side-road traffic has to give way to me. | No stop needed. |
| 3 | My turn crosses the oncoming lane; an oncoming car outranks me and would arrive before I am clear. | Slow, pull forward into the junction, hold at the waiting point. |
| 4 | I am inside the junction but not yet across the oncoming lane. | Keep holding. |
| 5 | The last oncoming car has passed, or the next is far away. | Finish the turn. |
| 6 | I am out of the junction on the side road. | Turn complete. |

Branches:

| Variant / driver | What differs | Behaviour |
|---|---|---|
| `clear` / sumo | Step 3 never happens. | Turns without stopping. Same road state as A/`clear`, different rule. |
| `oncoming_then_gap` / sumo | The nominal trace. | Stopped 7.2–10.7 s, 4 m past the entry line, then turns. |
| `oncoming_then_gap` / wait_in_junction | Same, driven through the agent interface. | Stopped at the waiting point 9.2–10.7 s. |
| `oncoming_then_gap` / turn_across | Ignores step 3. | Collision with the oncoming car at 8.1 s. |
| `minor_car_waiting` / sumo | A car sits at the side road's stop sign. It must give way to me and is doing so. | Turns without stopping. |
| `oncoming_turns_right` / sumo | The oncoming car turns into the same side road, so our paths merge instead of crossing. It still outranks me. | Holds at the waiting point, then follows it in. |

## C. `signal_straight` and `signal_left`: signalized four-way junction

| # | What the driver notices | What they do |
|---|---|---|
| 1 | Junction ahead with a signal; it is red for me. | Slow and stop at the line. |
| 2 | Stopped at the line, still red, cross traffic passing. | Hold. |
| 3 | The signal turns green and the junction ahead of me is empty. | Go. |
| 4 | I am out of the junction. | Done. |

Branches:

| Variant / driver | What differs | Behaviour |
|---|---|---|
| `green` / sumo | Green throughout. | Drives through without slowing. |
| `red_then_green` / sumo | The nominal trace. | Stopped 42.8–50.1 s, enters when green. |
| `red_then_green` / run_red | Ignores step 1. | Enters on red and passes within 8 m of a crossing car. |
| `yellow_far` / sumo | Green turns yellow while I can still stop comfortably. | Stops, waits through the red. |
| `yellow_near` / sumo | Green turns yellow when I can no longer stop comfortably. | Continues and clears the junction during yellow. |
| `signal_left` `oncoming_then_gap` / sumo | Green for me, but oncoming traffic also has green and outranks my left turn. | Enters, holds at the waiting point 7.2–9.3 s, then turns. Same shape as scenario B. |

Not staged yet: green while a late vehicle is still crossing the junction; the signal
turning red while the ego is waiting inside the junction.

## D. `roundabout`: enter, pass one exit, leave at the second

| # | What the driver notices | What they do |
|---|---|---|
| 1 | Roundabout entry ahead. No stop is required, but traffic on the ring outranks me. | Keep going, ready to slow. |
| 2 | A car on the ring is heading for my entry and would pass in front of me before I am in. | Slow or stop at the yield line. |
| 3 | It has passed my entry. | Enter. |
| 4 | I am on the ring. A car at the next entry has to give way to me and is doing so. | Keep going. |
| 5 | I have left the ring by my exit. | Done. |

Branches:

| Variant / driver | What differs | Behaviour |
|---|---|---|
| `empty` / sumo | Step 2 never happens. | Enters without stopping. Contrast with A/`clear`, where a stop is required. |
| `yield_to_circulating` / sumo | The nominal trace. | Stopped at the yield line 7.3–10.1 s. |
| `yield_to_circulating` / cut_in | Enters at step 2. | Enters directly in front of the ring car and is hit at 9.6 s. |
| `circulating_exits` / sumo | The ring car leaves by my own arm and never passes in front of me. | Enters at once, because SUMO knows its route. |
| `circulating_exits` / wait_until_it_exits | Same world, human knowledge: it *might* pass in front until it visibly leaves the ring. | Slows to a halt at the line, enters once the other car is on the exit. |
| `entering_car_yields` / sumo | The roles of step 2 are reversed: I am on the ring, the other car is at an entry. | Keeps going. |

## What changes the driver's behaviour, across all four

1. **Where I am relative to the junction**: ahead of it, at its line, inside it (before or after the point of no return), out of it.
2. **What my approach obliges me to do regardless of traffic**: stop (sign), or obey a signal aspect.
3. **Whether someone's path may meet mine** and has not yet passed that place.
4. **Who outranks whom** between me and that someone.
5. **Whether I would be clear before they arrive.**
6. **Whether I can still stop before the line** (the yellow-light question).
7. **Whether my path and my exit are physically free.**
8. **Another car's path becoming known**, which removes a possible conflict.
9. **Terminal facts**: collision, off the road, destination reached.

## What does *not* change behaviour, and so should not change the symbols

- Which side the other car comes from (left, right, oncoming), once its conflict and rank are known.
- How many conflicting cars there are.
- The junction's shape (T, cross, ring) and its coordinates.
- Whether a conflict is with one car followed by another, or one long wait for a single slow car.

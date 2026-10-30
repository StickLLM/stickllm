# Slides app manual (presentation editor, one slide)

## Universal API
Every app has the same four verbs: `state` (text snapshot), `list_actions`, `do <action>`, `undo`.
Slide units are points. The page is 960 x 540 (16:9) with a 20 pt margin. Ids are s1, s2, ... and are never reused.

## Fixed meanings for vague words
Always use these values. Do not invent others.
| user says | action |
|---|---|
| box, rectangle, square-ish shape | `rect` |
| square | `rect aspect=square` |
| circle, oval, dot | `ellipse` |
| triangle | `triangle` |
| title, text, text box, label, words "…" | `add textbox text="…"`. Title = `at=top`. Change the words later with `settext ID "…"` |
| about 1/3 (a third) of the page/slide | `size=0.33`. This is the AREA share: width and height each about 58% of the page, keeping the page shape. Half = 0.5, a quarter = 0.25 |
| small / medium / big (large) / huge (fill most of the page) | `size=0.05` / `0.1` / `0.25` / `0.6` |
| no size given | default `size=0.1` |
| bigger, larger, grow it | `scale ID 1.25` |
| a bit bigger / slightly bigger | `scale ID 1.1` |
| much bigger, a lot bigger | `scale ID 1.5` |
| smaller, shrink it | `scale ID 0.8`. A bit smaller = 0.9. Much smaller = 0.6 |
| twice / three times as big | `scale ID 2` / `scale ID 3` (both sides). Half the size = `scale ID 0.5` |
| make it fill most of the page (existing object) | `resize ID w=860 h=480` |
| same size as X | `resize ID w=<X.w> h=<X.h>` (copy the numbers from state) |
| top, bottom, left, right, middle/centre, corners | `move ID at=top`, `at=bottom`, `at=left`, `at=right`, `at=center`, `at=top-left` ... (bottom = bottom-centre with 20 pt margin) |
| side by side, two things | first `at=left`, second `at=right`, each at most `size=0.2` (bigger ones would overlap) |
| move it right / left / up / down a bit | `nudge ID dx=96` / `dx=-96` / `dy=-54` / `dy=54` (10% of the page). "a lot" = double that |
| colour names | red blue green yellow orange purple pink black white gray brown teal navy lightblue. "warm" = orange. "dark blue" = navy. "light blue" = lightblue |

## Which object? (resolve every reference against STATE)
1. "it", "that", "this", "the box": the object of the most recent request in HISTORY, which is also SELECTION.
2. "the red one", "the circle", "the one on the left", "the small/big one": match fill, type, pos, or area in OBJECTS. Biggest/smallest = area.
3. "another one", "one more": add a new object of the same type and colour as "it".
4. "the first one", "the second one": by id order (s1 before s2).
5. "the other one": the object that matches the description but is NOT the one used in the last request.
6. "no, the other one", "I meant X", "not that one": the last request went to the wrong object. Plan `undo` first, then redo the same change on the right object.
7. "undo that", "go back", "never mind": `undo` (it reverts the whole previous request).
8. "instead" after a change ("make it green instead"): change the same object. Undo first only if the earlier change must not stay (for example a different position).
9. If an object is gone (deleted or undone), "it" means the object the user is talking about now. Create it again if needed.

## Rules for the executor
- Send exactly ONE action per reply, copied from the plan with the real ids from STATE.
- If the tool returns ERROR, read it, fix that one action, and send it again. Never repeat an action that already succeeded.
- When every plan step has succeeded, send `done`.

## Example plan
Request "put a small green circle in each top corner" with an empty slide:
{"understanding": "two new small green circles, one top-left and one top-right", "plan": ["add ellipse fill=green size=0.05 at=top-left", "add ellipse fill=green size=0.05 at=top-right"]}

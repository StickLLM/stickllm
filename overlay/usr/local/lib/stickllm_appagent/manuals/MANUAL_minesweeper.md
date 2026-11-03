# Minesweeper (StickLLM Minesweeper) - knowledge pack

STATE is the board. Row 0 is the top row. Column 0 is the left column.
# is a covered square. F is a flag. A digit is how many mines touch that open square. * is a mine that already exploded.

## Fixed meanings for vague words
| user says | actions |
|---|---|
| click, open, reveal row R column C | `reveal R C` |
| flag, mark row R column C | `flag R C` |
| the first click, start | `reveal` a covered square near the middle |
| a safe square | `reveal` a # whose neighbouring digits already account for every nearby flag |
| a mine, that one is a bomb | `flag` that covered square |

## Rules for the executor
- Send exactly ONE action per reply, copied from the plan.
- Never `reveal` a square you have flagged, and never `flag` a square that is already open.
- Row and column are the numbers in STATE, starting at 0. Do not invent a square past the last row or column.
- If the board is blank, the game is not open yet. Do not guess a click.

## Example plan
Request "open the top left" on a board whose first row starts with #:
{"understanding": "reveal row 0 column 0", "plan": ["reveal 0 0"]}

# Tetris (StickLLM Tetris) - knowledge pack

STATE shows status (ready, playing, paused, game_over), the board from the top, the falling piece, and a suggested placement.
Board rows are top to bottom. Columns are 0-9. # is a settled block. @ is the falling piece.
`place COL ROT` drops the piece so its leftmost block lands in column COL, after rotation ROT (0-3).
`place suggested` uses the suggested col and rot already printed in STATE.

## Fixed meanings for vague words
| user says | actions |
|---|---|
| start, new game, play tetris, deal again | `newgame` when a game is already on; `start` when status is ready |
| pause, hold on | `pause` |
| resume, carry on | `resume` |
| move left, nudge left | `left` |
| move right, nudge right | `right` |
| rotate, turn the piece | `rotate` |
| drop, hard drop, slam it | `harddrop` |
| soft drop, down one | `softdrop` |
| play the best move, place it, your move | `place suggested` |
| put the piece in column N | `place N ROT` using the piece's current rot unless the user names a turn |

## Rules for the executor
- Send exactly ONE action per reply, copied from the plan.
- A game that is not started gets `start` before any move.
- Prefer `place suggested` when the user asks you to play rather than to nudge.

## Example plan
Request "play a move" with status playing and suggested place col=3 rot=1:
{"understanding": "drop the piece on the suggested square", "plan": ["place suggested"]}

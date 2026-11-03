# Solitaire (StickLLM Klondike card game) - knowledge pack

STATE lists the piles: waste, foundations f1-f4, tableau t1-t7. Top card is LAST; # is a face-down card.
Cards: rank A 2-9 T J Q K, suit S (spades) H (hearts) D (diamonds) C (clubs). Red: H D. Black: S C.

## Rules of the game
- Foundations build up by suit from A to K.
- Tableau piles build down in alternating colours (a red 9 on a black T). Only a K goes on an empty t pile.
- `draw` turns the next stock card onto the waste.

## Fixed meanings for vague words
| user says | actions |
|---|---|
| draw, deal, next card, flip the deck | `draw` |
| put the ace up, move X to the foundation | `move FROM->fN` (an empty f pile for an ace) |
| move the 9 of hearts onto the black ten | `move FROM->TO 9H` |
| play the waste card | `move waste->TO` |
| a good move, help me, what can I do | the first legal move you find: waste or tableau to a foundation, then tableau to tableau, else `draw` |
| new game, deal again, start over | `newgame` |
| undo that, take it back | `undo` |

## Rules for the executor
- Send exactly ONE action per reply, copied from the plan. Only plan moves that are legal in STATE.

## Example plan
Request "put the ace of spades up" with t4: "## AS":
{"understanding": "move the ace of spades from t4 to an empty foundation", "plan": ["move t4->f1"]}

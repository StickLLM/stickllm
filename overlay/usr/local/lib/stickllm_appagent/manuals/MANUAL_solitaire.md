# Solitaire (StickLLM Klondike card game) - knowledge pack

STATE lists the piles: waste, foundations f1-f4, tableau t1-t7. The top card is LAST. # is a face-down card.
Cards: rank A 2 3 4 5 6 7 8 9 T J Q K, suit S H D C. Red: H D. Black: S C.
Rank order going up: A, 2, 3, 4, 5, 6, 7, 8, 9, T, J, Q, K.

## Rules of the game (a move that breaks one is illegal; do not send it)
- Foundation (f1-f4): one card, same suit, next rank up. An empty foundation takes only an ace. 2S goes on AS. 2H does not go on AS. TH does not go on 9S.
- Tableau (t1-t7): the card you set down is the other colour and the next rank down. A red 9 goes on a black T. A red 9 does not go on a red T, and it does not go on a black 8. An empty tableau pile takes only a king.
- You may move a face-up run (the named card and the cards on top of it) only onto a tableau card that accepts the bottom card of that run.
- A face-down card (#) cannot be moved. Draw turns the next stock card onto the waste. Do not move from stock.
- If no move is legal, send `draw`. If the stock is empty too, say so and send nothing else.

## Fixed meanings for vague words
| user says | actions |
|---|---|
| draw, deal, next card, flip the deck | `draw` |
| put the ace up, move the ace to the foundation | `move FROM->fN` only when that card is an ace and that foundation is empty, or it continues the same suit |
| move the 9 of hearts onto the black ten | `move FROM->TO 9H` only when TO's top card is a black T |
| play the waste card | `move waste->TO` only when the waste's top card is legal on TO |
| a good move, help me, what can I do | the first legal move: waste or tableau onto a foundation, then tableau onto tableau, else `draw` |
| new game, deal again, start over | `newgame` |
| undo that, take it back | `undo` |

## Rules for the executor
- Send exactly ONE action per reply, copied from the plan.
- Before a `move`, name the card and the destination top card and check colour and rank. If the check fails, do not send that move.
- Do not send `click`. It drops a card on a pile you did not choose.

## Example plan
Request "put the ace of spades up" with t4: "## AS" and f1: "-":
{"understanding": "AS is a face-up ace and f1 is empty, so it may start that foundation", "plan": ["move t4->f1"]}

Request "move the 9 of hearts onto the ten of hearts" with t1: "9H" and t3: "TH":
{"understanding": "9H on TH is the same colour, which is illegal, so no move", "plan": ["draw"]}

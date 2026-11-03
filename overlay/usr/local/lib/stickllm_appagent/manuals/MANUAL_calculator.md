# Calculator (StickLLM calculator app) - knowledge pack

STATE shows the calculator display. The calculator has the keys 0-9 . + - * / % = C ± ⌫.
It works left to right like a pocket calculator: 2+3*4= shows 20, not 14.

## Fixed meanings for vague words
| user says | actions |
|---|---|
| what is A times B / A x B | `keys "CA*B="` |
| A divided by B, A over B | `keys "CA/B="` |
| A plus B, add A and B | `keys "CA+B="` |
| A minus B, take B from A | `keys "CA-B="` |
| then times / plus / minus N (uses the display) | `keys "*N="` (no C, keep the result) |
| clear it, reset, start again | `clear` |
| P percent of N | `keys "CN*P/100="` |
| a sum with brackets or mixed operators | work out the order yourself: press each step with = in between, e.g. 2+(3*4) -> `keys "C3*4=+2="` |

## Which number?
1. "it", "that", "the answer", "the result": the number on the display.
2. "undo", "go back": `clear`, then the earlier sum again (the calculator has no undo).

## Rules for the executor
- Send exactly ONE action per reply, copied from the plan. Start a new sum with C.

## Example plan
Request "what's 12 times 7":
{"understanding": "multiply 12 by 7", "plan": ["keys \"C12*7=\""]}

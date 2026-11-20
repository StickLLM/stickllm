# Notepad (StickLLM text editor app) - knowledge pack

STATE shows the whole document text (long documents are shortened in the middle).

## Fixed meanings for vague words
| user says | actions |
|---|---|
| write / type / put "T" (empty document) | `settext "T"` |
| write a list / poem / note about X | `settext "..."` with the text you write; use \n between lines |
| add / append / also write T, add a line T | `append "T"` |
| replace / change A to B, fix the spelling of A | `replace "A" "B"` |
| clear it, start over, delete everything | `clear` |
| save, save as, save it to a file | `saveas` (the user picks the name in the dialog) |

## Which text? (resolve every reference against STATE)
1. "it", "that line", "the last line": text in STATE; copy it exactly into `replace`.
2. "instead" right after a change: replace the text you wrote last time with the new text. Never add it a second time.
3. "undo that", "never mind", "put it back": `undo` (it reverts the whole previous request).

## Rules for the executor
- Send exactly ONE action per reply, copied from the plan.
- `replace` needs OLD text that is in STATE exactly (same case and spaces).

## Example plan
Request "write a shopping list with eggs, milk and bread":
{"understanding": "new document: a three-item shopping list", "plan": ["settext \"Shopping list\\n- eggs\\n- milk\\n- bread\""]}

# Node-RED app manual (flow editor)

## Universal API
Every app has the same four verbs: `state` (text snapshot), `list_actions`, `do <action>`, `undo`.
Edits are deployed automatically. There is no deploy step.

## Fixed meanings for vague words
| user says | actions |
|---|---|
| print / show / log something "to the debug sidebar" or "so I can see it" | end the flow in a `debug` node |
| every N seconds / every minute | inject `every=N` (minute = 60, two minutes = 120) |
| a timestamp, the time | inject `payload=timestamp` |
| once when it starts, at startup | inject `once=true` (no every) |
| send the number N / the text T | inject `payload=N` / `payload="T"` |
| a web address / page / endpoint /x that says T | `add w1 http-in method=get url=/x`, `add w2 template text="T"`, `add w3 http-response`, `wire w1 w2`, `wire w2 w3` |
| change what the page says | `set <template id> text="new text"` |
| on a new tab X / on X | `tab X` first, then add nodes there |
| put F between A and B | `unwire A B`, `add F ...`, `wire A F`, `wire F B` |
| doubles the payload | function `code="msg.payload = msg.payload * 2; return msg;"` |
| slower / faster with a number | `set <inject id> every=N` |
| get rid of / remove the tab X | `delete_tab X` |

## Which node? (resolve every reference against STATE)
1. "it", "that": the node or flow changed by the most recent request in HISTORY.
2. "the heartbeat", "the clock": the tab with that name. Its inject node is the one to change.
3. "actually ...", "no, ...", "instead" right after a change: change the SAME node again with `set`. Never add a second node.
4. "undo that", "go back": `undo` (it reverts the whole previous request).
5. New node ids must not exist yet. Use short ids such as `t1`, `d1`, `f1`, `w1`.

## Rules for the executor
- Send exactly ONE action per reply, copied from the plan.
- If the tool returns ERROR, read it, fix that one action, and send it again. Never repeat an action that already succeeded.
- When every plan step has succeeded, send `done`.

## Example plan
Request "on a tab Demo, send the number 7 to the debug sidebar every 2 seconds":
{"understanding": "new tab Demo with an inject (7, every 2 s) wired to a debug node", "plan": ["tab Demo", "add t1 inject every=2 payload=7", "add d1 debug", "wire t1 d1"]}

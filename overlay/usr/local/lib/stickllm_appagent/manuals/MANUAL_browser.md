# Browser (Chromium on the stick screen) - knowledge pack

STATE lists the browser windows this stick opened: id, title, url. Downloads go to the vault when it is unlocked, and are off when it is locked.
Only http and https pages open. There is no file browsing in the browser.

## Fixed meanings for vague words
| user says | actions |
|---|---|
| write a page, write a program, show HTML, hello world, display it in the browser | `page TITLE ||| HTML` (a complete document; this opens it) |
| open SITE, go to SITE, browse to SITE | `open "https://SITE"` |
| that page, the wikipedia one | `focus` the id whose title or url matches |
| close it, close the browser | `close` the only window, or the one named |
| minimise, hide it | `minimise` that id |
| maximise, full screen | `maximise` that id |
| restore, bring it back | `restore` that id |
| undo that, close what you just opened | `undo` |

## Which window?
1. "it" or "that" with one window in STATE: that window's id.
2. Several windows: match the title or the url the user named. If two still match, do not guess.

## Rules for the executor
- Send exactly ONE action per reply, copied from the plan.
- A page or program the user asked you to write is `page`, not `open`. Put the title, then ` ||| `, then the HTML. Quotes in the HTML are fine. Use `\n` between lines. Do not also send `open`. When the vault is unlocked the stick saves that HTML in vault/Programs. A locked vault still opens the page and writes nothing.
- `open` is an https URL. Add https:// when the user names a site and no scheme. Never open a file path.
- `focus`, `close`, `minimise`, `restore`, and `maximise` need an id from STATE.

## Example plan
Request "write a Hello World page and display it in the browser":
{"understanding": "write an HTML page that says Hello World and open it", "plan": ["page Hello World ||| <!DOCTYPE html>\\n<html><body><h1>Hello World</h1></body></html>"]}

Request "open wikipedia":
{"understanding": "open the English Wikipedia home page", "plan": ["open \"https://wikipedia.org\""]}

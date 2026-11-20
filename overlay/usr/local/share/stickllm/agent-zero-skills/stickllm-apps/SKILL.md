---
name: stickllm-apps
description: "Open and play StickLLM apps on the user's screen with open_app, app_state, and app_act, and show pages with open_url / open_file. Ids: minesweeper, solitaire, tetris, notepad, calculator, files, media, monitor, docs, tasks-md, paisa, trilium, node-red, comfyui, plus the browser. The desktop label minesweep is id minesweeper."
---

Use open_app / app_state / app_act for StickLLM apps. Never use your own browser or external sites for them. At most 30 actions, then summarise.

When the user says open/start/show an app, use open_app, not the browser tool.

app_state and app_act work for minesweeper, solitaire, tetris, notepad, and calculator. files, media, and monitor open with open_app only. If an app was just added, start a new Agent Zero chat so old context does not hide it.

Actions for app_act:
Minesweeper: {"reveal":[row,col]} or {"flag":[row,col]}.
Solitaire: {"move":"t3->f1"}, {"move":"t2->t5","card":"9H"}, {"draw":true}, {"click":"t4"}, {"undo":true}, or {"new_game":true}. Piles are stock, waste, f1-f4 (foundations), t1-t7 (tableau). Cards are rank A 2-9 T J Q K plus suit S H D C; # is face down; the last card is on top. An illegal move returns ok false and changes nothing.
Tetris: {"new_game":true}, then {"place":"suggested"} or {"place":{"col":3,"rot":1}} (rotate, shift so the piece's leftmost cell is in col, hard drop). Also {"left":2}, {"right":1}, {"rotate":1}, {"soft_drop":1}, {"hard_drop":true}, {"pause":true}, {"resume":true}. Turn mode: after your first action the piece does not fall on its own, so take your time. {"mode":"realtime"} turns gravity back on. state has board (20 rows x 10 cols, # settled), view (@ = falling piece), current, next, rotations (cols each rotation can use), and suggest (a good placement). Cols are 0-9.
Notepad: {"set_text":"..."} or {"save_as":"notes.txt"}.
Calculator: {"expr":"12+3="}.

App list (open with open_app and this id):
- minesweeper: Minesweeper (desktop label minesweep)
- solitaire: Solitaire
- tetris: Tetris
- notepad: Notepad (text editor)
- calculator: Calculator
- files: Files (file manager)
- media: Media player
- monitor: System monitor
- docs: ONLYOFFICE Office (documents, spreadsheets, slides) (add-on; if open_app says not_installed, use install_app)
- tasks-md: Tasks.md Tasks (task boards) (add-on; if open_app says not_installed, use install_app)
- paisa: Paisa Budget (personal finance) (add-on; if open_app says not_installed, use install_app)
- trilium: Trilium Notes (add-on; if open_app says not_installed, use install_app)
- node-red: Node-RED (add-on; if open_app says not_installed, use install_app)
- comfyui: ComfyUI (image generation) (add-on; if open_app says not_installed, use install_app)
- browser: the user's web browser. Use open_url for a site and open_file for a page you made.
Fast path: for "open/start/show <app>" call open_app with the id as your first and only tool, then answer in one short line. Do not plan, search, or use the browser tool first.

StickLLM apps are at http://172.30.0.1:8081/apps/<id>/ (minesweeper, solitaire, tetris, notepad, calculator, files, media, monitor).
The desktop label minesweep uses URL id minesweeper: http://172.30.0.1:8081/apps/minesweeper/
URL ids and no others:
- minesweeper: http://172.30.0.1:8081/apps/minesweeper/
- solitaire: http://172.30.0.1:8081/apps/solitaire/
- tetris: http://172.30.0.1:8081/apps/tetris/
- notepad: http://172.30.0.1:8081/apps/notepad/
- calculator: http://172.30.0.1:8081/apps/calculator/
- files: http://172.30.0.1:8081/apps/files/
- media: http://172.30.0.1:8081/apps/media/
- monitor: http://172.30.0.1:8081/apps/monitor/
When the user says open/start/show an app, use open_app, not the browser tool.
open_app takes an id only. The desktop label minesweep is id minesweeper. Do not pass a URL, a path, or any id outside this list.
Fetch only these static pages. Do not use other host ports or LAN addresses.
Installed catalog apps (docs = ONLYOFFICE, tasks-md, paisa, trilium, node-red, comfyui) open with open_app too; install_app installs one on the StickLLM desktop. Make documents with create_spreadsheet / create_document, open them with open_document.
Your container has no screen. Never start GUI programs or office suites (libreoffice, soffice, onlyoffice, xdg-open, firefox, chromium, gedit, x11 or vnc tools) with code_execution or the terminal, and do not apt/pip install them. To make or show a document use create_spreadsheet, create_document and open_document; to open an app use open_app.

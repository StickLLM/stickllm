# StickLLM app agent

Small HTTP service beside llama-server. The chat UI sends one request for one app; the local model
(Qwen3.5-4B, thinking off) reads the app manual + live state + this session's history and writes a plan;
the frozen plan checker (`checker.py`, sha256 6efd3e88...188fa) flags bad plans and the model gets one re-ask;
the plan lines then run against the app (hybrid exec: on an ERROR the model may repair the line, at most
2 tries, `skip` allowed). Each request is one undo step.

API (loopback `127.0.0.1:8795`; browsers use the gateway at `/appagent/...`):

* `GET  /apps` -> `[{name, description, connected?}]`
* `POST /act   {app, request, session}` -> `{understanding, plan, results, state, check_flags, reask, ...}`
* `POST /undo  {app, session}` -> undoes the last request
* `GET  /state?app=&session=` -> manual-format state text plus `objs` / `flows`
* `POST /reset {app, session, start}` (tests)

Adapters (`adapters/`): `name`, `manual`, `state()`, `list_actions()`, `do(line)`, `undo()`, plus
`begin_request()` / `end_request()`.

* `onlyoffice`: the presentation open in the ONLYOFFICE editor. The editor loads the system plugin
  `plugin/` (autostart, set by `stickllm_docs.editor_config(agent_plugin_url=...)`); it long-polls
  `/oo/poll`, runs `Api.*` JS with `callCommand`, posts results to `/oo/result`. State is read from the
  real document every request.
* `nodered`: the Node-RED add-on admin API (127.0.0.1:8105).
* `slides`: in-memory simulator (tests).

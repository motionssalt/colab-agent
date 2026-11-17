# Wire protocol v1

Only HTTP and WebSockets. No SSE. A session supports multiple viewers but only one active runner. Connection strings are URL-safe base64 JSON `{"url":"https://tunnel.trycloudflare.com","token":"<control capability>"}`. Tokens use 32 random bytes. The static site receives this as a fragment, removes the fragment from history, and saves it in localStorage. Treat browser storage and the one-tap link as a password. Forget connection removes it. No capabilities in URL query parameters.

## Site → brain `/control`

WebSocket starts with `{"type":"auth","token":"..."}` within five seconds; no other message is processed before authentication. Rejected credentials close 4401. The runner uses an Authorization header instead. `GET /health` is a minimal unauthenticated liveness check. `GET /state` requires `Authorization: Bearer <control token>`.

After welcome, send JSON objects:

| type | fields | action |
|---|---|---|
| chat | text | new task or inbox message while working |
| new_task | text | stop old task, clear history, start fresh |
| stop | none | cancel model request and interrupt PTY |
| takeover | enabled (boolean) | pause agent, allow user keyboard input |
| input | data | literal UTF-8 terminal input, only in takeover |
| resize | cols, rows | fit terminal (20–240 columns, 5–100 rows) |
| ping | none | application-level pong |
| restart_runner | none | checkpoint workspace and dispatch replacement |

Brain → site: `welcome` includes model, runner boolean, agent status, takeover boolean, bounded scrollback and recent events. `terminal {data}` contains ANSI terminal bytes decoded incrementally as UTF-8. Render with a terminal emulator, never innerHTML. `chat {role,text}`, `event {tool?,text}`, `error {text}`, `agent_status {status}`, `runner_status {online,remaining_s?}`, `takeover {enabled}`, `pong {time}`. Terminal chunks are ordered. Reconnect welcome replays recent scrollback; clear the old display first. Pings and HTTP checks are every 45s. Reconnect uses exponential backoff capped at 30s. Pings do not defeat Colab platform limits.

## Runner → brain `/runner`

Outbound worker sends `Authorization: Bearer <runner token>` during upgrade. Newest authenticated runner wins; outstanding requests fail explicitly on replacement. Initial `hello {worker_id,screen}` identifies a worker process. Output: `terminal {worker_id,seq,data}`, `worker_status {remaining_s}`, `result {id,result}`. Sequence numbers deduplicate replays within one worker. Reconnect may lose bounded output under sustained backpressure; screen and subsequent output recover visibility. No binary frames.

Brain sends `call {id,tool,args}`, `interrupt`, `takeover {enabled}`, `input {data}`, and `resize {cols,rows}`. Worker tools: run(command, timeout_s), send_keys(keys), read_screen(), write_file(path,content). One command at a time. Interrupt cancels the current command, not its already-applied filesystem effects. Results include exit_code, output and timed_out, or an error. Never automatically repeat a disconnected command without checking state.

Frames are limited to 1 MiB, control text to 20k chars, raw input to 60k, queues and scrollback bounded. Maximum 100 incoming messages/second per connection. Over-limit connections close 1008/1009. Slow consumers close 1013. Browser uses auth-first because browser WebSocket APIs cannot set Authorization headers. Both tokens use constant-time comparison.

## State and trust

State version 1 is saved to state/session.json on workspace. Config includes model and context/step limits, never credentials. Restore requires an explicit notebook resume choice. GH_TOKEN exists only in the worker shell; notebook PAT stays in notebook memory. Public workspace and Releases expose saved conversations and output: do not give the agent personal or secret tasks. This is not a sandbox for untrusted multi-user execution.

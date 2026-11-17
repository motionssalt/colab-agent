# BUILD PROMPT: colab-agent (agentic terminal, version 1)

## STEP 0: CREDENTIALS (read first)

```
GITHUB_OWNER = motionssalt
GITHUB_PAT = [REDACTED — provide privately]
CLOUDFLARE_API_TOKEN = [REDACTED — provide privately]
CLOUDFLARE_ACCOUNT_ID = [REDACTED]
```

- This is the PAT you (the builder) use to create the repo, push code, set up Pages and run Actions. It must be a classic PAT with `repo` and `workflow` scopes. If the PAT belongs to a different account than `GITHUB_OWNER`, use the PAT's own account as the owner and record that in BUILD_STATE.json `decisions`.
- The Cloudflare lines are used only to deploy the static control-panel site (`site/`) to **Cloudflare Pages**. Victor does NOT want GitHub Pages. Store both as GitHub Actions repo secrets (`CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`) for the deploy workflow only; they must never be available to `runner.yml`, the brain, the notebook or the agent.
- Never commit secrets, tokens, keystores or personal data. The repo is PUBLIC. Never write any credential value into BUILD_STATE.json (secret NAMES only), into logs, or into any file.
- If a value above is still a placeholder, do everything that does not need it first (code, tests with mocks) and ask Victor only if the work genuinely cannot continue.
- Do not confuse this builder PAT with the PAT that end users paste into the Colab notebook at runtime. That is a separate feature you are building (see the design below).

## HARD RULE: NO APPLET WORK. USE THE PREBUILT HOST FRONT-END FROM THE REPO

This whole task happens in the GitHub repository. Some host environments (Google AI Studio in particular) insist on a runnable web front-end and time out or crash after about 12 to 13 minutes if none exists. Victor never looks at that front-end (he installs and downloads from GitHub Releases and uses the real product), so you must never spend effort designing one.

- The front-end lives in the repo folder `host-frontend/` (entry file `host-frontend/index.html`).
- Only if your host requires a front-end (for example Google AI Studio): as your very first step after reading BUILD_STATE.json, check whether `host-frontend/` exists in the repo. If it exists, pull it and use it exactly as it is (copy its files into the host's app slot). Do not redesign, extend or improve it.
- If it does not exist, create this minimal placeholder in seconds, commit it to `host-frontend/index.html` immediately, and use it (every later session then pulls it instead of creating one):

```html
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>colab-agent</title></head><body style="font-family:sans-serif;padding:24px"><h1>colab-agent: build in progress</h1><p>Work happens in the GitHub repository. Releases are on the repo's Releases page.</p></body></html>
```

- Hosts that do not require a front-end: do nothing here. Do not create it.
- Never add features to it, never use it to preview or mock the work, and never add other files whose only purpose is previewing. The only deliverables are commits in the repository and GitHub Releases. Spend all your effort on the task itself.
- IMPORTANT NOTE FOR THIS PROJECT: this project's real product includes a control-panel website in the `site/` folder. That is a real requested deliverable and is separate from `host-frontend/`. Build `site/` as specified below. Never build any other front-end or preview.
- If a host default conflicts with this rule, this rule wins, but never leave the host without a front-end.

## ROLE AND AUTONOMY

You are the sole builder of this project and you have full autonomy. This brief describes the outcome and the constraints, not step-by-step instructions. You decide the implementation details, the libraries and the file layout (within the constraints), and you keep going without asking questions.

- **Do not stop to ask Victor for anything (clarification, confirmation, choices) unless the work genuinely cannot continue.** When something is ambiguous, pick the most sensible default, proceed, and record the assumption in BUILD_STATE.json `decisions`. If something is truly blocked, do all other possible work first, record the blocker, and ask in one short message at the end.
- Victor works only from an Android phone (Termux). He has no desktop and no local CLI. You work in your own environment and push to GitHub. GitHub Actions does the testing and running.
- **Finish each queue item completely before starting the next one.** Never start item N+1 while item N is half done.
- **No skimming.** Every item gets full, proper work: understand it, implement it thoroughly, verify it against its acceptance criteria, and fix what turns up before marking it `done`. Late items get the same depth as the first.
- Related items may be done together if they touch the same files, but each is verified individually.

## PROJECT BACKGROUND

**What it is.** `colab-agent` is a free, self-hosted autonomous AI agent whose **brain runs in a Google Colab notebook** (a local LLM served by Ollama on Colab's free T4 GPU) and whose **computer is a GitHub Actions runner**. Victor watches the agent work live, in a real terminal, in his phone browser, and can type to the agent while it works.

**Why it exists.** Victor (brand MOTIONSALT, Nigeria) cannot afford paid AI agents or paid APIs and keeps hitting usage limits. He wants an agent with no API limits: the model runs on Colab (free GPU), and all heavy work runs on GitHub Actions (free and unlimited minutes for public repos), so the Colab does only the thinking. Someday he will pay for better AI; until then this is his free fallback. He was inspired by a friend who built an app that runs from Colab: you run the Colab, it gives a link, you paste the link into the app and it connects automatically, and the app pings the Colab every 45 seconds to keep it alive.

**Who uses it.** Victor first. Later other people should be able to open the notebook, paste their own GitHub PAT, and run it. Later still it may become an Android app, so keep the connection protocol clean and documented (the site is just one client).

**Version 1 scope (this prompt): the agentic terminal only.** A working end-to-end loop: user gives a task, the Ollama brain decides, commands are typed into a live terminal on the Actions runner, the output goes back to the brain, repeat, and the user sees everything live and can interrupt or add messages. Web search works through the terminal. Files can be saved to GitHub Releases. **No extra skills yet** (no app-building skill packs, no special workflows). Victor will confirm this version works before any skills are added. Do not add them.

## ARCHITECTURE (agreed design, follow it)

```
 Phone browser                    Google Colab (free T4)                 GitHub Actions runner (public repo)
 -------------                    ----------------------                 -----------------------------------
 site/ (Cloudflare Pages) <--WSS-->  brain server (FastAPI/uvicorn)  <--WSS--  runner worker (outbound connection)
  chat + live terminal             Ollama (qwen3:14b default)               PTY + tmux running bash
  stop + status + ping             agent loop + tools                       search/fetch helper commands
                                   cloudflared quick tunnel                 gh CLI, GITHUB_TOKEN (repo-scoped)
```

1. **Colab notebook (the brain).** Installs Ollama, pulls the model, starts the brain server, starts a `cloudflared` quick tunnel (free, no account), and prints the link for the site. The notebook has one final cell that keeps running (printing a calm heartbeat line) so Colab never considers the notebook idle.
2. **Brain server.** A Python server (FastAPI + uvicorn or similar) with two WebSocket endpoints: one for the site (control) and one for the runner worker. It owns the agent loop, the conversation state, the Ollama client, and the inbox of user messages.
3. **Runner worker (the hands).** GitHub Actions cannot receive inbound connections, so the runner connects OUT to the Colab tunnel URL over WebSocket and gives the brain a real shell. The brain sends tool calls; the worker executes them in a PTY and streams all terminal output back.
4. **Site (the control panel).** A static page in `site/`, deployed to Cloudflare Pages (one shared deployment that every user opens; the connection string lives only in the URL fragment and the browser, so the host never sees it). The user pastes the connection string printed by the notebook (or opens the one-tap link the notebook prints) and it auto-connects. It shows chat, the live terminal, a stop button and a connection status, and it pings the Colab every 45 seconds. It auto-reconnects.
5. **Persistence.** Colab and runner disks vanish. Conversation state and work go to the repo so a restarted session can resume (see Resume below). Deliverable files go to GitHub Releases.

### How the Colab starts the runner (important, follow exactly)

The repo is public, so workflow logs and workflow_dispatch inputs are PUBLIC. Therefore:

- The notebook generates per session: a random **control token** (site to brain) and a random **runner token** (worker to brain). Use `secrets.token_urlsafe(32)` or better. Compare with `hmac.compare_digest`.
- The notebook uses the user's PAT (entered at setup) with the GitHub API to store `AGENT_TUNNEL_URL` and `AGENT_RUNNER_TOKEN` as **repository Actions secrets** (encrypt with the repo public key using PyNaCl sealed box, as the GitHub API requires), then triggers `runner.yml` via `workflow_dispatch` **with no sensitive inputs**. Secrets are masked in Actions logs.
- The runner job reads those secrets, starts the worker, and the worker connects out to `wss://<tunnel>/runner` with the runner token. The brain accepts only one runner connection at a time (the newest valid one wins).
- The user's PAT is used ONLY by the notebook for: creating the repo if missing, pushing the scaffold files, setting the two secrets, dispatching/cancelling the runner workflow. It is **never** passed to the model, the agent's prompt, the terminal, the runner, or any log. It is held in memory only (use `getpass` or Colab Secrets) and never written to disk or the repo.
- The agent, when running commands on the runner, only has the runner's built-in `GITHUB_TOKEN` (exposed to its shell as `GH_TOKEN` so the preinstalled `gh` CLI works). That token is scoped to this one repository and expires when the job ends. The workflow's `permissions:` must be the minimum needed: `contents: write` (commits, releases). Do not give the agent anything broader.

### Setup flow for other users (must work)

Anyone opens the notebook (one "Open in Colab" badge in the README), sets runtime to T4 GPU, runs the setup cell, and pastes their PAT. The notebook then:
1. Verifies the PAT (classic, `repo` + `workflow` scopes) and gets the account name.
2. Uses repo name `colab-agent` under that account (configurable at the top of the notebook as `REPO_NAME`). If it does not exist, **creates it as a public repo** and populates it from the template source (`motionssalt/colab-agent`, default branch, downloaded as a tarball and pushed). If it exists, it ensures the runner files and workflow are present and up to date (fast-forward from the template, never overwriting the user's `workspace` branch content).
3. Does not deploy any site: every user opens the same shared control-panel site. The notebook has a `SITE_URL` setting at the top (default: the Cloudflare Pages URL of Victor's deployment) and uses it to print the one-tap link.
4. Installs Ollama, pulls the model, starts the server and tunnel, sets the secrets, dispatches the runner, and prints the connection string and the one-tap site link.

For Victor, the repo `motionssalt/colab-agent` is both the template source and his own workspace repo, so step 2 simply finds it existing.

## FEATURES AND BEHAVIOR (version 1)

**Agent tools** (kept few and simple, because the model is a small local one):
- `run(command, timeout_s)`: types the command into the live terminal (it must be visibly typed and echoed in the same terminal Victor watches), waits until it finishes or times out, returns the exit code and the tail of the output (bounded size, head and tail kept). Use a robust completion marker or prompt hook, and handle commands that never finish (timeout, then report and leave the terminal usable, send Ctrl-C if configured).
- `send_keys(keys)`: sends raw keys/text (including Ctrl-C, Enter, arrow keys) for interactive programs.
- `read_screen()`: returns the current visible terminal screen (via tmux `capture-pane` or equivalent).
- `write_file(path, content)`: writes a file on the runner reliably without heredoc typing (small models break on heredocs). Echo a one-line note in the terminal (for example `# wrote path (N bytes)`) so the user still sees it.
- `message_user(text)`: sends a visible chat message to the user (progress, questions only when truly stuck).
- `finish(summary)`: ends the current task and shows the summary.

**Web search and page reading** are done as shell commands on the runner, so they happen visibly in the terminal and use the runner's IP (not Colab's, which gets blocked more often). The workflow installs and puts on PATH two helper commands:
- `search "query" [-n 8]`: DuckDuckGo via the `ddgs` package, no API key; prints numbered title, URL and snippet.
- `fetch URL [--max-chars N]`: downloads a page and prints clean readable text (trafilatura), bounded output.
The agent is simply told these exist. No separate web tool is needed.

**Saving results:** the agent saves deliverables with the preinstalled `gh` CLI, for example `gh release create` / `gh release upload`, and commits work with git. The system prompt must tell it how (with exact example commands that work with `GH_TOKEN`). Releases must use unique tags and must never delete earlier releases unless the user asks.

**Working area:** on the runner the agent works in `~/work`, which is a clone of the repo's `workspace` branch (create the branch in bootstrap if missing). It commits and pushes there often. By default it must not touch `runner/`, `brain/`, `site/`, `notebook/` or `.github/` unless the user explicitly asks. Full autonomy otherwise: if the user tells it to delete or change something in the repo, it does it.

**Interaction while working:**
- The user can send a chat message at any time. The brain keeps an inbox; the agent loop checks it between steps and injects the message to the model as a new user message marked as a mid-task message. The model must adapt.
- A **Stop** button aborts the in-flight model generation, interrupts the running command (Ctrl-C into the PTY) and puts the agent back to idle, ready for the next message. The state must remain consistent.
- The user can also **type directly into the terminal** (takeover). Add a toggle on the site: "I control the terminal" versus "Agent controls" so keystrokes from the user and from the agent do not collide. Default: view-only for the user, with a button to take over; while taken over the agent waits.
- Terminal output streams live and in order to all connected site clients. A late-joining or reconnecting client gets the recent scrollback (bounded).

**The model:**
- Ollama only. No hosted LLM APIs, no API keys for model providers. Do not add any.
- Default model `qwen3:14b` (Q4, fits the T4 with a 16k context). The notebook exposes a model dropdown/setting at the top with at least `qwen3:14b`, `qwen2.5-coder:14b`, `qwen3:8b` (faster) and a free-text override. Set sensible Ollama env vars for a T4 (keep model loaded, flash attention, quantized KV cache) and set `num_ctx` explicitly (default 16384).
- Tool calling: use Ollama's native tool-calling through its OpenAI-compatible or native chat API when the model supports it, **and** implement a strict-JSON fallback (parse the model's text for one JSON action, validate it against the tool schemas, and on malformed output send a short repair message and retry up to 3 times before reporting the failure to the user). Small models are unreliable here, so this needs real care and tests.
- Thinking/reasoning mode of Qwen3 is slow: make it a setting (default off for the agent loop, with a note), and strip reasoning tags from anything shown or fed back.
- One tool call per step. Keep the loop disciplined: max steps per task (default 60, configurable), detect a model repeating the same command or the same error over and over and nudge it or stop and report, and never let a failure loop spin forever.
- Context management is essential at 16k: truncate tool outputs (head and tail), and when the conversation approaches the context budget, summarise older turns into a short running summary and keep the system prompt, the latest task and the recent steps intact.
- Write a **tight system prompt** at `brain/prompts/system.md`, designed for a weaker model: short, concrete rules and a few worked examples of correct tool use (a search, a fetch, writing a file, committing and uploading a release asset). Rules to include: one action at a time, read the real output before continuing, never invent command output, prefer small steps, install missing tools with apt/pip when needed, call `finish` when done, ask the user only when truly stuck, keep chat messages short. Keep it as small as it can be while working.

**Session length and resume:**
- A runner job lasts at most 6 hours and takes about 20 to 40 seconds to boot. Use `timeout-minutes` below the limit. The worker should announce when it has about 10 minutes left; the brain then tells the agent to commit and push its work, and the brain dispatches a fresh runner and the agent continues in the new one (work state comes back from the repo `workspace` branch). Use a workflow `concurrency` group so only one runner runs at a time and a new dispatch cancels the old one.
- The worker exits on its own if the brain has been unreachable for 10 minutes (so a dead Colab does not leave a runner burning).
- The brain saves conversation state (messages, running summary, current task, config but never tokens) to `state/session.json` on the `workspace` branch every few steps and when idle, using the repo token via the runner or the PAT in the notebook (your choice, log it). On a Colab restart the notebook offers to resume from it.
- The notebook handles Colab disconnects honestly: the site shows "brain offline" and does not pretend.

**Site (`site/`, static, no build step needed; vendor any library such as xterm.js into the repo instead of relying on a CDN):**
- Connection panel: one field to paste the connection string (the string encodes the tunnel URL and the control token) or auto-connect when opened via the one-tap link (put the secret in the URL fragment `#...` so it is never sent to any server). Remember it in localStorage and auto-reconnect. A clear status: connecting, connected, brain online with model name, runner online or booting, runner offline, brain offline.
- Chat panel: messages from the user, the agent's chat messages, and compact event lines for tool calls (what the agent ran) so the user can follow.
- Live terminal panel (xterm.js, fits mobile) showing the runner terminal, with the take-over toggle.
- Stop button, a "new task" action, and a button to restart the runner.
- Pings every 45 seconds (a WebSocket ping/pong plus an HTTP `/health` check) and shows time since the last pong. Auto-reconnect with backoff.
- Mobile-first layout that works on a phone browser. **Functionality only. Do not do a visual polish pass** (see Out of scope).
- Document the wire protocol (messages between site and brain, between brain and runner) in `docs/PROTOCOL.md` so that a future Android app can reuse it. Use WebSockets and plain HTTP only. **Do not use Server-Sent Events** (cloudflared quick tunnels do not support them).

**Security rules (non-negotiable):**
- Public repo: no secrets in git, ever. Add a CI check (for example a simple secret-pattern scan) that fails the build if a token pattern is committed.
- Control and runner tokens are per session, random, compared in constant time, and never printed in Actions logs. The worker must be silent on stdout (no terminal output in Actions logs); the terminal is streamed over the WebSocket only. Use `::add-mask::` for anything sensitive anyway.
- Rate-limit and size-limit incoming WebSocket messages on the brain. Reject unauthenticated connections immediately.
- The user's PAT never reaches the model, the runner or the repo (see above).
- The Cloudflare token and account ID exist only as repo secrets used by `deploy-site.yml`. `runner.yml` must not reference them.

## ENVIRONMENT AND CONSTRAINTS

- Everything must be free: Colab free tier (T4, roughly up to 12 hour sessions, idle and quota disconnects possible), GitHub Actions standard runners on a public repo (2 cores, 7 GB RAM, job limit 6 hours), Cloudflare Pages (static site only), cloudflared quick tunnels (no account, URL changes every run, no SLA).
- The Ollama install on Colab uses the official install script and needs the machine's usual tools (check for `zstd` and install if missing); run `ollama serve` in the background and wait until it is ready before pulling.
- The notebook must be a valid `.ipynb`. Keep the notebook thin: put real logic in importable Python files under `notebook/` or `brain/` that the notebook fetches from the repo (clone or tarball), so fixes ship through git without editing the notebook. Generate the `.ipynb` from a readable source script and commit both, or write it carefully by hand, but validate that it opens (nbformat validation in CI).
- You cannot run Colab or a T4 yourself. Prove everything you can in CI (see item F8) and be honest in `known_issues` about what was not tested on real Colab.
- Victor cannot use a desktop or Termux to debug. The notebook and site must show clear, plain-English errors (for example "PAT is missing the workflow scope", "No GPU runtime: switch to T4").

## REPO

- **Repo:** `motionssalt/colab-agent` (use `GITHUB_OWNER/colab-agent`), **public**. Create it if it does not exist; if it already exists, continue in it.
- Suggested layout (you may adjust and record why): `notebook/` (notebook and bootstrap code), `brain/` (server, agent loop, prompts), `runner/` (worker, helper commands), `site/` (control panel), `.github/workflows/` (`runner.yml`, `deploy-site.yml`, `ci.yml`, `e2e.yml`), `docs/` (`PROTOCOL.md`, `FIRST_RUN.md`, `BUILD_PROMPT.md`, `DECISIONS.md`), `host-frontend/`, `BUILD_STATE.json`, `README.md`.
- Branches: `main` (code), `workspace` (the agent's work and saved session state).

## STATE AND RESUME PROTOCOL

You are one of possibly several stateless AIs. Continuity lives in the repository.

- **On start: read `BUILD_STATE.json` first** (if it exists), then continue from the first queue item or next step not marked `done`. Do not restart or redo finished work.
- Create `BUILD_STATE.json` in the **first commit** and update it after every meaningful step, committing it with the code. Names of secrets only, never values.
- Save a copy of this whole prompt in the repo as `docs/BUILD_PROMPT.md` in the first commit, and keep `docs/DECISIONS.md` for decisions with reasons.
- Schema:

```json
{
  "project": "colab-agent",
  "repo": "owner/colab-agent",
  "goal": "one-paragraph description",
  "status": "not_started | in_progress | blocked | complete",
  "current_phase": "phase id",
  "phases": [
    { "id": "1", "name": "...", "status": "pending | in_progress | done | blocked", "notes": "..." }
  ],
  "queue": [
    { "id": "F1", "title": "...", "status": "pending | in_progress | done | blocked", "notes": "what changed and how it was verified" }
  ],
  "completed": ["what is finished and verified"],
  "next_steps": ["exact next actions, in order"],
  "decisions": ["decision + reason, so nobody re-litigates it"],
  "known_issues": ["bugs, blockers, things that failed and why, and what was NOT testable on real Colab"],
  "deployment": { "urls": ["site URL"], "release_tag": "", "secrets_expected": ["AGENT_TUNNEL_URL", "AGENT_RUNNER_TOKEN"] },
  "last_updated": "ISO timestamp",
  "last_session_note": "what the last AI was doing when it stopped"
}
```

## COMMIT AND PUSH DISCIPLINE

Builders often die before committing, so:
- **Commit and push very frequently**: after every file or small unit of work, not at the end of a phase.
- First commit: repo scaffold, `BUILD_STATE.json`, `docs/BUILD_PROMPT.md`, `host-frontend/index.html`. Push immediately, before any real code.
- Use meaningful commit messages. Never leave work uncommitted while starting something new.
- Every push must leave the repo in a state the next AI can understand from BUILD_STATE.json alone.
- If a GitHub Actions run (CI or e2e) fails, fix it before moving on.

## QUEUE (work in order, one item at a time, finish each fully)

**F1. Scaffold.** Create the repo, layout, `README.md` (what it is, the Open in Colab badge pointing at the notebook, how to use it in plain steps), `BUILD_STATE.json`, `docs/BUILD_PROMPT.md`, `docs/DECISIONS.md`, `host-frontend/index.html`, `.gitignore`, a `ci.yml` skeleton with the secret-pattern scan. Done when: everything is pushed, CI runs green.

**F2. Runner worker and runner workflow.** `runner/worker.py` plus `runner.yml`. The worker starts a tmux session with bash on a PTY, connects out to the brain with reconnect and backoff, executes `run`, `send_keys`, `read_screen`, `write_file`, streams every byte of terminal output, supports Ctrl-C interrupt, handles the take-over mode, reports time-left, exits after 10 minutes without a brain. The workflow reads the two secrets, installs tmux, `ddgs` and `trafilatura`, installs the `search` and `fetch` helper commands on PATH, clones the `workspace` branch to `~/work`, sets `GH_TOKEN`, uses `concurrency` and `timeout-minutes`, and prints nothing sensitive. Done when: unit tests for the worker pass in CI against a mock brain, including command completion detection, timeouts, Ctrl-C, truncation and reconnect; `search` and `fetch` run in CI and return real results (or a clearly handled failure).

**F3. Brain server and agent loop.** FastAPI server with the site and runner WebSocket endpoints, token auth, `/health`, inbox handling, stop handling, scrollback buffer, the agent loop, the Ollama client with native tool calling and the strict-JSON fallback and repair loop, context management and summarising, loop guards, state save and load, and the system prompt. Done when: tests with a scripted fake LLM pass in CI (multi-step task, mid-task user message, stop, malformed tool call repair, repeated-command guard, context truncation, resume from saved state).

**F4. End-to-end CI test (localhost).** `e2e.yml`: start the brain, start the worker pointed at it, use a tiny real Ollama model (for example `qwen3:0.6b` or `qwen2.5:0.5b`) or a scripted LLM stub, send a task like "run `echo hello` and then `search python` and finish", and assert that the command appears in the terminal stream, the output returns to the model, and the task finishes. Done when: it passes in Actions. Also add a second job `e2e-tunnel` that does the same through a real `cloudflared` quick tunnel inside Actions to prove WebSockets work across the tunnel (best effort: if the Actions network blocks it, record that in `known_issues` and keep the localhost test as the gate).

**F5. Site.** Build `site/` as specified (connection panel, chat, live terminal, take-over toggle, stop, 45 second pings, auto-reconnect, status), and `docs/PROTOCOL.md`. Done when: a headless-browser smoke test (Playwright or similar) in CI loads the site, connects to a locally started brain with a scripted LLM, shows the terminal output of a command and shows a user message round trip. Functional only.

**F6. Cloudflare Pages deploy.** Create the Cloudflare Pages project (name `colab-agent`, production branch `main`) using the Cloudflare credentials from Step 0 via the API or wrangler, and add `deploy-site.yml` that deploys `site/` with `wrangler pages deploy` on every push that changes `site/`, using the repo secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` (set them as repo secrets with the builder PAT; names only in BUILD_STATE.json). Add `site/_headers` with sensible security headers (no caching of `index.html`). Set the notebook's default `SITE_URL` to the resulting `*.pages.dev` URL. Done when: the live URL (record it in BUILD_STATE.json `deployment.urls`) loads the site and a push to `site/` redeploys it.

**F7. Colab notebook and bootstrap.** The notebook and its Python bootstrap: GPU check with a plain error, PAT entry (getpass or Colab Secrets) and verification of scopes, repo creation or update from the template, Ollama install and model pull with progress, server start, cloudflared download and start (parse the quick tunnel URL), secret storage with sealed-box encryption, runner dispatch, connection string and one-tap link printing, the keep-alive final cell with calm heartbeat, resume offer, and an "all off" cell that cancels the runner run. Done when: unit tests with a mocked GitHub API cover repo creation, secret encryption, dispatch, scope errors and idempotent re-runs; the notebook passes nbformat validation; and a **live check** using the builder `GITHUB_PAT` against the real repo sets the two secrets and dispatches `runner.yml` with a dummy tunnel URL, then confirms the run started, the worker failed to connect gracefully, and the Actions log contains no secret values.

**F8. Hardening and docs.** Re-read the security rules and verify each one with a test or a log inspection. Resume across a runner rotation (simulate a runner being replaced mid-task). Write `docs/FIRST_RUN.md`: a short phone-friendly checklist for Victor (open the notebook in Colab, choose the T4 runtime, run the setup cell, paste PAT, wait for the link, open it, give the agent a first task such as "search the web for the latest stable Python version and tell me"), plus what to do when Colab disconnects, plus known limits. Update the README. Done when: all CI is green and BUILD_STATE.json lists honestly what has not been tested on real Colab.

If an item is truly blocked (missing credential, external service down), record it as `blocked` with the exact reason, skip it, and report it at the end. Difficulty or ambiguity alone is not a reason to skip.

## OUT OF SCOPE (do not build)

- Any skills or special workflows (app building, APK compiling, code review packs, etc.). They come after Victor confirms version 1 works.
- Any hosted LLM API or paid service, or any model-provider API key.
- Cloudflare Workers, D1 or any backend (only the static Pages site is deployed), GitHub Pages, an Android app wrapper, user accounts, multiple concurrent sessions, multi-agent setups.
- A UI refinement or visual polish pass. If you finish the queue, **stop and report back**. A UI refinement is a separate task for a fresh session, started only when Victor asks. Any session that reaches such a step must stop and report instead of doing it.
- Any extra preview front-end beyond `host-frontend/` and the requested `site/`.

## DEFINITION OF DONE AND FINAL REPORT

Done when F1 to F8 are `done` (or honestly `blocked` with reasons), CI and e2e are green, the site is live on Cloudflare Pages, `BUILD_STATE.json` is final and committed, and the live dispatch check from F7 passed.

Final report (short, in your last message): the repo URL, the live site URL, the notebook "Open in Colab" link, which parts were proven in CI and which could not be tested on real Colab, any blocked items, the chosen defaults you logged in `decisions`, and one line telling Victor the first thing to do (open `docs/FIRST_RUN.md`).
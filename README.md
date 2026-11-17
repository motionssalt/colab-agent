# colab-agent

A free, self-hosted agentic terminal: **Ollama in Google Colab thinks; GitHub Actions runs the commands; your phone shows chat and a live terminal.** No hosted model APIs or model-provider keys. Version 1 only — no skill packs or Android wrapper.

[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/motionssalt/colab-agent/blob/main/notebook/colab_agent.ipynb)

**Control panel:** https://colab-agent.pages.dev · **Start:** [phone-first checklist](docs/FIRST_RUN.md) · **Protocol:** [v1](docs/PROTOCOL.md) · **Build record:** [BUILD_STATE.json](BUILD_STATE.json)

## Use it

Choose a Colab **T4 GPU**, run notebook setup, and paste a **GitHub PAT** into its hidden prompt (any valid user PAT works: a **classic PAT** with `repo` + `workflow` scopes, or a **fine-grained PAT** with repository **Actions**, **Secrets**, **Contents**, and **Workflows** set to Read and write — plus Account **Administration: Read and write** if auto-creating the repo, or create an empty public `colab-agent` repo first). Tap the private control-panel link, run the heartbeat cell, and give the agent a task. Setup creates your public repository and runner; everyone uses the same static control panel. No site deployment is needed for other users. When finished, interrupt heartbeat and run **All off**.

Defaults: `qwen3:14b`, context 16384, thinking off, 60 steps/task. `qwen2.5-coder:14b`, faster `qwen3:8b` and a model-name override are available. Site and runner use outbound WebSockets through an account-free quick tunnel; no SSE. Browser pings every 45s do not defeat platform limits.

## What you can do

Watch real command input/output, send mid-task messages, stop generation/commands, take terminal control, search/fetch the web visibly, and ask the agent to commit files or publish unique GitHub Releases. Workspace and conversation state persist on the separate `workspace` branch. A new runner can resume after a checkpoint.

## Trust and safety

The PAT stays in notebook memory only; only a repository-scoped, job-lived GH_TOKEN reaches the agent shell. Per-session control and runner capabilities are distinct. Cloudflare credentials are used only in deploy-site.yml. Source and CI have secret-pattern scanning. The archived build prompt is redacted. Rotate credentials originally provided to the builder.

**Your repository, conversation state, files and Releases are PUBLIC.** This agent runs arbitrary commands and is not a hardened multi-user sandbox. Do not give it secrets, personal data or untrusted tasks. Sharing a control link grants shell control. Stop cannot undo commands already applied.

## Tested / not yet tested

GitHub Actions: unit/integration tests, real tmux, localhost and real cloudflared tunnel, mobile Chromium, notebook/schema validation, encrypted-secret API mocks, CLI watchdog, and workspace plus conversation recovery across runner replacement. Also tested a real workflow_dispatch with encrypted session secrets, an unreachable dummy tunnel, graceful worker exit and public-log inspection.

The live static site is deployed to Cloudflare Pages with its own isolated deployment workflow. **A real Google Colab/T4 model session was not available to the builder.** Model fit/speed/quality and Colab quotas/disconnects require a first real run. This is a first-run release candidate, not a guarantee of unlimited free compute. Read FIRST_RUN before starting.

## Development

Python 3.11+, tmux; install requirements-dev.txt. Run `pytest -q`, `python tests/e2e_check.py`, and `python scripts/scan_secrets.py`. For browser testing install Playwright Chromium and run `python tests/e2e_check.py --browser`. Generate the committed notebook with `python notebook/generate.py`.

Template updates are fast-forward Git-data commits, never force-push; modified template-managed files cause a clear stop rather than overwriting local changes. workspace is never overwritten. Other users do not receive Victor's Pages deployment workflow or build-state credentials. The static xterm dependencies and MIT licenses are vendored, not loaded from a CDN.

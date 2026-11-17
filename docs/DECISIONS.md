# Decisions

- Use Python asyncio, FastAPI and tmux; no paid services.
- No host preview app is required. Only site/ is a product UI.
- Credential values are removed from the archived build brief.
- Cloudflare account-scoped token validates on the account endpoint, not the user-token endpoint. Deploy only static site/ to Pages.

- Default qwen3:14b / 16384 context / thinking off / 60 steps. Real T4 testing is explicitly deferred to the first user run.
- Native Ollama tools first, strict JSON fallback and three repair retries. Non-Qwen3 models are not sent an unsupported thinking option unless requested.
- Use bounded extractive running summaries rather than spending extra GPU calls on summarization.
- tmux owns the PTY; pipe-pane streams its raw bytes to a private FIFO. An initial view-only handshake must not send Ctrl-C before bash is ready.
- Actions already uses /home/runner/work. Give the agent a separate HOME under runner.temp so its requested ~/work remains an isolated workspace clone.
- Context/state writes use worker-relative ~/work (never Colab's home expansion), preserve the agent cwd with subshells, and serialize RPC calls.
- Runtime users need classic repo+workflow PATs. Builder fine-grained permissions were verified directly; live dispatch run 44135450081 passed and its public logs were inspected for all supplied/session credentials.
- Template bootstrap uses in-memory tarballs and Git Data API commits, not PAT-bearing git remotes or credential files; local modifications abort rather than being overwritten. Other accounts do not get deploy-site.yml.
- Use a scripted model in CI to test the mechanism deterministically; model reasoning quality is not claimed to be proven by those tests.
- Release is marked a prerelease until Victor confirms a real Colab/T4 session. No skills or visual polish were added.

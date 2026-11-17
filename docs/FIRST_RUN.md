# First run — on your phone

**Start here.** No desktop or Termux commands are needed.

1. Open the notebook using the Open in Colab badge on the repository README.
2. In Colab choose **Runtime → Change runtime type → T4 GPU**, then save/reconnect. Free GPU quota is not guaranteed.
3. Run **1. Set up colab-agent**. Leave the defaults initially. Paste any **GitHub PAT** (classic or fine-grained) only into the hidden input prompt. Do not put it into a code cell.
   - **Classic PAT:** select `repo` and `workflow` scopes.
   - **Fine-grained PAT:** grant repository **Actions**, **Secrets**, **Contents**, and **Workflows** (Read and write) on your `colab-agent` repo. To let the notebook auto-create the repo, choose All repositories and also grant Account **Administration** (Read and write); or create an empty public `colab-agent` repo on GitHub first and select only that repo.
4. Wait for the model download, brain and tunnel. The first setup can take several minutes. The notebook creates/updates your public `colab-agent` repository and starts its runner. It never gives your PAT to the model or terminal.
5. Tap **Open your control panel**, or paste the private connection string into https://colab-agent.pages.dev. This link is a password: do not share it or notebook output.
6. Run **2. Keep running**. Return to the control-panel tab and wait for **Runner online**. A cold runner may take a minute or more.
7. Send: **Search the web for the latest stable Python version and tell me, with the official source URL.** Watch the terminal. Only real command results should be used.
8. **Stop** interrupts the command and model. To type in the terminal yourself, choose **I control the terminal**. Choose **Agent controls** to return control. Send another chat message to redirect an active task.
9. At the end, interrupt the heartbeat cell, then run **3. All off**. Check the repository Actions page if necessary; no runner should remain active.

## If something disconnects

**Site says brain offline:** return to Colab. If the runtime is gone, rerun setup, choose to resume saved state, open the new private link, and send “continue”. Old tunnel URLs and tokens stop working. If only the site lost its network, it reconnects automatically and replays recent scrollback.

**Runner offline:** allow a minute for startup, then use **Restart runner** or rerun notebook setup. Inspect the Actions run for setup errors. If a command lost its connection, inspect files/screen before repeating it: side effects might already have happened.

**Wrong token:** use the newest notebook link. **Forget connection** clears this browser's stored connection. Anyone with that connection string can control your shell.

**PAT scope/permission error:** for a classic PAT, enable both `repo` and `workflow` scopes; for a fine-grained PAT, select the `colab-agent` repo and enable **Actions**, **Secrets**, **Contents**, and **Workflows** (Read and write). Never send your PAT in chat, terminal, issues, or screenshots. Rotate the builder credentials originally supplied to this build after handoff.

**No GPU:** switch runtime to T4. Free quota may require trying later. **Out of memory / very slow:** choose `qwen3:8b`, reduce NUM_CTX to 8192, and rerun setup. Default Qwen3 14B/T4 behavior has not been tested on a real Colab session by the builder.

## What is public / what is private

Repository code, workspace files, saved conversations (`state/session.json` on workspace), Releases and workflow logs are public. Do not give the agent personal or secret tasks. The notebook PAT stays in notebook memory. The temporary GH_TOKEN can write only this repository and expires with the runner. Deployment secrets are used only by the site deployment workflow.

Connection tokens live in memory and browser localStorage; fragment links are not sent to the static host. Notebook output intentionally contains the private control capability. Clear outputs before sharing a notebook. The app is a personal autonomous shell, not a security boundary against a hostile local process or prompt injection.

## Limits and verification

Pings and the heartbeat do not bypass Colab quotas, inactivity policies or maximum session duration. GitHub and Cloudflare service terms/quotas apply; free availability is not promised. Standard runner lifetime is below six hours, with checkpoint-and-replace near expiry. An unreachable brain causes the worker to exit after ten minutes. Search providers can rate-limit; helpers report failure rather than invent results. Stop cannot undo filesystem or remote side effects.

CI proves fake-model tool execution, native/JSON schema validation and repairs, mid-task messages, cancellation, context bounds, real tmux timeout recovery/reconnect, real localhost and quick-tunnel WebSockets, mobile Chromium chat/terminal/takeover, sealed GitHub secrets, notebook validation, CLI watchdog exit, and workspace/conversation recovery across an actual simulated runner replacement. A live Actions dispatch was tested with a dummy tunnel and clean public logs. Real T4 model speed, memory use, model decision quality and Colab disconnect behavior still need this first phone run.

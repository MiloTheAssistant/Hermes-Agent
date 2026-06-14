# Claude Code Brief v2.3 — OpenClaw Decommission + Hermes Agent (Streams A–E)

Supersedes `hermes-migration-brief-streams-AB.md` / `-CDE.md` (v1) and reconciles
`plans/HermesCodex.md`. Rewritten 2026-06-12 after verifying all three documents against
the live machine and the `hermes-agent` source. Design goal per John: **low drag, high
speed** — fewest moving parts, fastest responses, full tools/skills/MCP capability.

-----

## Current Version + Tracking Status

| Field | Value |
|-------|-------|
| Current version | v2.3 |
| Status | Post-execution final plan, retained as a tracked migration/audit artifact |
| Last live validation | 2026-06-14 14:15 CDT |
| Source checkout | `/Volumes/BotCentral/Users/milo/repos/hermes-agent` |
| Tracking branch | `codex/track-hermes-migration-plan` |
| Upstream Hermes base | `7433d5f0eb22ae95c2aa5bd4cffa55df382573af` |
| Hermes version | `Hermes Agent v0.16.0 (2026.6.5)` |
| Runtime state | Hermes live; Telegram outbound delivery verified; OpenClaw removed; OpenHermes quarantined/inert |
| Remaining live gate | None for the approved Telegram DM channel |

## What changed v2.2 → v2.3 (live-channel completion)

| Topic | v2.2 said | v2.3 says | Why |
|-------|-----------|-----------|-----|
| Telegram authorization | Pairing/home-channel setup still pending | Telegram user `Milo` is approved in the pairing store | The pending Telegram DM request was owner-approved locally. |
| Telegram home channel | `TELEGRAM_HOME_CHANNEL` missing | Home channel is set for the Telegram DM | Hermes can now resolve the bare `telegram` delivery target. |
| Outbound smoke | Blocked by missing home channel | `hermes send --to telegram` succeeded | Live smoke sent to the Telegram home channel on 2026-06-14 at 14:15 CDT. |

## What changed v2.1 → v2.2 (post-execution reconciliation)

| Topic | v2.1 said | v2.2 says | Why |
|-------|-----------|-----------|-----|
| Tracking | Brief existed as a local plan file | Brief is promoted to a tracked repo artifact | The migration plan is now part of the audit trail instead of an untracked local note. |
| Hermes state | Planned update/install/migration work | Hermes is installed, current, and running from the local checkout | Verified on 2026-06-14: `hermes version` reports upstream `7433d5f0` and `Up to date`. |
| OpenClaw | Decommission work to run through Phase 6 | Phase 6 passed and guarded finalizer completed | `.openclaw-retired`, OpenClaw postgres volume, Mission Control images, app/runtime surfaces, and cron recurrence are gone. |
| Terminal backend | Docker backend via OrbStack after Stream A | `terminal.backend=local` for low-drag Mac Mini EA operation | Current operating target is fast local assistant work. Docker remains installed but is not on the critical path. |
| Ollama local daemon | Re-bind local Ollama to localhost | Local Ollama is not exposed on `11434` | Current Phase 6 gate passes only when no broad local Ollama listener is present. |
| Telegram send | Run `hermes send --to telegram` after service install | First set `TELEGRAM_HOME_CHANNEL` or send `/sethome` from the target Telegram chat | Gateway is connected in polling mode, but channel directory has `0` Telegram targets until a home channel is set. |

-----

## What changed v2 → v2.1 (HermesCodex reconciliation — all claims verified)

| Topic | v2 said | v2.1 says | Why |
|-------|---------|-----------|-----|
| Hermes install | Fresh `install.sh` (creates `~/.hermes/hermes-agent`) | **Update the EXISTING source install in place** | Verified: `~/repos/hermes-agent` already holds a working `.venv` install — v0.11.0 (tag v2026.4.23), HEAD detached, 5,866 commits behind upstream, `~/.local/bin/hermes` missing. Running install.sh would create a second parallel install. |
| Memory migration | Hand-rolled markdown copy + paste-into-session | **First-party `hermes claw migrate`** (dry-run → review → apply), curation as a post-pass | Verified: Hermes ships an OpenClaw migration tool covering SOUL.md, MEMORY.md/USER.md → Hermes memories, workspace instructions, messaging settings, exec-approval allowlists, skills, TTS assets. Plus `hermes claw cleanup` for leftovers. |
| Docker | Not covered | Stream A decommissions the **5 `openclaw-mission-control-*` containers** + postgres volume | Verified: webhook-worker is running RIGHT NOW (restart policy keeps reviving it); frontend/backend/db/redis exited 6 weeks ago; volume `openclaw-mission-control_postgres_data` exists. |
| OpenHermes | Bootout + delete plist, keep repo | **Quarantine** (bootout, plist moved aside not deleted, archives of `.openhermes` + `repos/OpenHermes`) | HermesCodex is right that it's not OpenClaw — softer default until John explicitly retires it. Both paths verified to exist. |
| Repo remotes | Not covered | `origin` = NousResearch (upstream), `milo` = MiloTheAssistant fork — **deviation from HermesCodex, confirmed by John 2026-06-12** | HermesCodex wants origin=fork. But `hermes update` pulls via git from the checkout's remote — if origin is a fork that lags, updates stall. Keeping origin=upstream makes `hermes update` just work; push the fork explicitly. |
| Secrets in migration | n/a | **Never pass `--migrate-secrets`** | The migrate tool's Discord-settings import would carry the OLD (pre-rotation) token into Hermes. Rotated tokens enter only via `hermes gateway setup`. |

Everything else from v2 stands: native `ollama-cloud` primary, no LiteLLM, no qmd, no
self-hosted Langfuse, MiloCache backups, exact-label decommission, don't-hand-patch the
gateway plist.

**Stream ordering (changed):** B (update install) must run **before** C (`claw migrate`
needs a current Hermes build — v0.11.0 may predate the command), and A's stop/archive
must complete before C applies. So: **A-inventory → B → A-decommission → C → D → E.**
Phase 6 gate unchanged at the end.

**Architecture (do not deviate without a logged decision):**

- Primary model: `minimax-m3` via native **`ollama-cloud`** provider — direct to
  `https://ollama.com/v1`. No proxy, no local daemon in the critical path.
  (Per HermesCodex, confirmed: minimax-m3 is NOT in the local Ollama today. Cloud
  availability is checked live by the setup picker — do not hardcode; fallback below.)
- Fallback (tool-call gate fails or model absent): one-command switch via `hermes model`
  to native `minimax` provider, OpenRouter (`minimax/minimax-m3`), or Nous Portal.
- Vision auxiliary: `codex` provider (ChatGPT Pro OAuth). Compression/web-extract/
  session-search: `auto`.
- Local models: local Ollama stays installed but out of the critical path — optional
  named custom provider (`ollama-local`) later. Current live state has no Ollama
  listener on `11434`; if re-enabled later, bind it to 127.0.0.1 only.
- Sub-agents: `delegate_task`, 3 parallel children inheriting the primary model.
  (`delegation.provider` overrides support openrouter/nous/zai/kimi-coding/minimax —
  not custom/local. Don't plan local-model sub-agents.)
- Execution backend: `terminal.backend=local` for low-drag Mac Mini assistant operation.
  Docker/OrbStack remain available for explicit container work, but they are not the
  default Hermes execution path.
- One Hermes profile. Sub-agents + kanban replace the 16-agent roster.

**Environment gotchas (verified):**

- `$HOME` = `NFSHomeDirectory` = `/Volumes/BotCentral/Users/milo` (lowercase `milo`).
- `hermes gateway install` writes its plist to the BotCentral LaunchAgents dir (derived
  from account home). Expected — launchd demonstrably loads agents from there today.
  The reboot test passed on 2026-06-14; Plan B in Stream D Step 7 is retained only
  for future gateway persistence failures.
- launchd doesn't source `~/.zshrc`. Hermes bakes absolute `HERMES_HOME` + full `PATH`
  into its plist itself. The hand-written backup plist (Stream E) must do the same.
- `~/.hermes` already exists from the old v0.11.0 usage — Stream B reviews it
  (`hermes config check` / `config migrate`), does not assume fresh.
- API keys/tokens never appear in chat output or committed files.

**Manual steps John performs himself (not Claude Code):**

1. Rotate Telegram bot token (BotFather) and Discord credentials (dev portal) — BEFORE Stream D.
2. Create an **ollama.com account API key** (Ollama Cloud — `ollama signin` on the local daemon is not sufficient).
3. `hermes setup` / `hermes gateway setup` wizards; ChatGPT OAuth for Codex vision.

**Decisions — LOCKED by John, 2026-06-12:**

1. **Remotes:** `origin` = NousResearch (upstream), `milo` = MiloTheAssistant fork. `hermes update` pulls upstream directly; fork is pushed explicitly.
2. **OpenHermes:** quarantine (bootout, plist + archives to MiloCache quarantine, directories left in place, no deletion).
3. **Workspace instructions:** NOT migrated — `--workspace-target` is never passed (verified: the migrate tool cleanly skips that category when the flag is absent). `~/repos/hermes-agent` remains the Hermes **source repo** (the install lives there); it is not the EA's workspace.

-----

## File Checklist

| Stream | Path | Action |
|--------|------|--------|
| A | `/Volumes/MiloCache/archives/openclaw-final-YYYYMMDD.tar.gz` | Create — full `.openclaw` archive (3.8G source), `chmod 600` |
| A | `/Volumes/MiloCache/archives/openclaw-mc-postgres-YYYYMMDD.tar.gz` | Create — Mission Control DB volume archive, `chmod 600` |
| A | `/Volumes/MiloCache/quarantine/openhermes/` | Create — OpenHermes plist + archives of `.openhermes` and `repos/OpenHermes` |
| A | `~/migration-assets/` | Create — markdown memory corpus (real paths below) |
| A | `/Users/milo/Library/LaunchAgents/{ai.openclaw.gateway,ai.openclaw.smart-memory,com.milo.smart-memory}.plist` | Bootout + delete |
| A | `/Volumes/BotCentral/Users/milo/Library/LaunchAgents/{ai.openclaw.gateway,ai.openclaw.node,com.openclaw.sync-decisions}.plist` | Bootout + delete |
| A | `/Volumes/BotCentral/Users/milo/Library/LaunchAgents/com.openhermes.milo.plist` | Bootout + MOVE to quarantine |
| A | user crontab entry running `MiloTheAssistant-Milo/tools/gh-sync.sh` and writing `.openclaw/sync.log` | Remove; it recreates `.openclaw` every 15 minutes |
| A | `/Applications/OpenClaw.app` | Quit, remove from Login Items, trash |
| A | `/opt/homebrew/lib/node_modules/openclaw` | `npm uninstall -g openclaw` |
| A | Docker: `openclaw-mission-control-{frontend,backend,webhook-worker,db,redis}-1` | Stop + rm (volume kept until Phase 6 gate) |
| A | `~/Library/{Application Support/OpenClaw,WebKit/ai.openclaw.mac,HTTPStorages/ai.openclaw.mac,Logs/OpenClaw,Caches/ai.openclaw.mac}` + `~/Library/Preferences/ai.openclaw.*.plist` | Archive + delete after services are stopped |
| A | `/Volumes/BotCentral/Users/milo/.openclaw` | Rename → `.openclaw-retired` (delete only after Phase 6 gate) |
| B | `~/repos/hermes-agent` | Restore `main`, update to upstream, reinstall `.venv`, link `hermes` on PATH |
| C | (managed by `hermes claw migrate`) | Pre-migration snapshot of `~/.hermes` is automatic |
| C | `~/.hermes/legacy-openclaw/` | Create — curated legacy corpus |
| D | `/Volumes/BotCentral/Users/milo/Library/LaunchAgents/ai.hermes.gateway.plist` | Created and OWNED by `hermes gateway install` — inspect, don't patch |
| E | `/Volumes/BotCentral/Users/milo/Library/LaunchAgents/com.milo.hermes-backup.plist` | Create — nightly backup job; use Python launcher under `~/.hermes/bin` and logs under `~/.hermes/logs` |
| E | `/Volumes/MiloCache/backups/hermes/` | Create — backup target |

Third-party plists to LEAVE ALONE in the BotCentral LaunchAgents dir:
`ai.perplexity.xpc`, `com.elgato.StreamDeck`, `com.google.GoogleUpdater.wake`,
`com.google.keystone.agent`, `com.google.keystone.xpcservice`.

-----

## Stream A — Part 1: Inventory (run first, before anything)

```bash
launchctl list | grep -E "openclaw|openhermes|com\.milo\." | grep -v "com.apple"
lsof -i :18789 -i :18790 -i :3000 -P
ls /Users/milo/Library/LaunchAgents/
ls /Volumes/BotCentral/Users/milo/Library/LaunchAgents/
docker ps -a --format '{{.Names}} {{.Status}}' | grep openclaw
docker volume ls | grep -i "openclaw|mission"
pgrep -fl "OpenClaw|openclaw"
pm2 list 2>/dev/null
crontab -l 2>/dev/null | grep -i openclaw
```

Record output. Expected (verified 2026-06-12): `ai.openclaw.gateway` on :18789,
`com.openhermes.milo` on :18790, OpenClaw.app + Sparkle updater processes, the
webhook-worker container Up, four containers Exited, port 3000 free.

All decisions are locked (see header) — proceed to Stream B.

-----

## Stream B — Update the Existing Hermes Install + Model Wiring

### Step 1 — Preserve worktree state, restore main

```bash
cd /Volumes/BotCentral/Users/milo/repos/hermes-agent
git status                                   # untracked plans/*.md are safe; note them
git restore plans/gemini-oauth-provider.md   # undo the stray deletion (tracked file)
git checkout main
```

(Claude Code worktrees under `.claude/worktrees/` are separate checkouts — untouched.)

### Step 2 — Remotes (decision locked: origin=upstream, milo=fork)

```bash
git remote -v                                # currently: origin = NousResearch — keep
git remote add milo https://github.com/MiloTheAssistant/Hermes-Agent.git 2>/dev/null || true
git fetch origin
git reset --hard origin/main                 # bring main to upstream tip
git push milo main --force-with-lease        # sync the fork
```

### Step 3 — Reinstall into the existing venv, fix PATH

```bash
source .venv/bin/activate 2>/dev/null || true
uv pip install -e ".[all]"
hermes --version                             # must show the current upstream build
# Make `hermes` work outside the venv (~/.local/bin/hermes is currently missing):
mkdir -p ~/.local/bin
ln -sf "$(pwd)/.venv/bin/hermes" ~/.local/bin/hermes
which hermes && hermes --version             # from PATH, no venv activation
```

### Step 4 — Health + config migration (the old `~/.hermes` predates this build)

```bash
hermes doctor          # use --fix for auto-remediable items
hermes config check
hermes config migrate  # pull in new config options
```

### Step 5 — John: Ollama Cloud API key, then wire the primary model

```bash
hermes setup
```

Selections: Provider **Ollama Cloud** (native — not the custom-endpoint path), API key
from ollama.com, model **minimax-m3** picked from the live-discovered list. If absent
from the list, stop — apply the fallback tree (native `minimax` provider / OpenRouter /
Nous Portal via `hermes model`) and record the winner.

```bash
hermes config show | grep -i -E "provider|model"
```

### Step 6 — Tool-call quality gate

```bash
hermes   # 1. ask it to run `ls` via tool call
         # 2. ask a 3-step task (read file, summarize, write file)
```

Malformed tool calls or dropped chains → switch provider via `hermes model`, re-run gate.

### Step 7 — Execution backend (local default; Docker optional)

```bash
docker info --format '{{.OperatingSystem}}'
hermes config show | grep -i -A8 '^terminal:'
hermes config set terminal.backend local
```

Current live state is `terminal.backend=local` for low-drag Mac Mini EA operation.
Docker/OrbStack remain installed for explicit container work, but they are not the
default Hermes execution path. If Docker is reintroduced later, review the `terminal:`
block in `hermes config edit`: `docker_image`, `docker_mount_cwd_to_workspace: true`,
`docker_run_as_host_user: true`. The container cannot see host volumes like MiloCache —
that's why backups are host-level (Stream E).

### Step 8 — Local Ollama hygiene

```bash
lsof -i :11434 -P | grep LISTEN              # normally no listener; never *:11434
```

Current live state keeps local Ollama off the critical path and not listening on
`11434`. If local Ollama is re-enabled later, persist a localhost-only binding through
Ollama's supported launch settings for this install. If no supported persistence
mechanism is available, document that and make the Phase 6 reboot gate fail unless
`lsof -i :11434 -P | grep LISTEN` shows only `127.0.0.1`/`localhost`, never `*:11434`
or `0.0.0.0:11434`.

Optional named custom provider `ollama-local` (→ `http://localhost:11434/v1`) only
when local small-model duty is actually wanted. Skip at install time.

### Step 9 — Vision auxiliary

John completes ChatGPT OAuth via `hermes model` → Codex, then in `hermes config edit`:

```yaml
auxiliary:
  vision:
    provider: "codex"
```

**Stream B complete when:** `hermes --version` is current and works from PATH outside
the venv; `hermes doctor` clean; tool-call gate passed and the winning provider recorded.

-----

## Stream A — Part 2: Decommission (after Stream B; B doesn't touch OpenClaw)

### Step 1 — Stop everything

```bash
# System-drive agents
for L in ai.openclaw.gateway ai.openclaw.smart-memory com.milo.smart-memory; do
  launchctl bootout gui/$(id -u)/$L 2>/dev/null || true
done
# External-volume agents (ai.openclaw.gateway label already unloaded; dup plist deleted later)
for L in ai.openclaw.node com.openclaw.sync-decisions com.openhermes.milo; do
  launchctl bootout gui/$(id -u)/$L 2>/dev/null || true
done
osascript -e 'quit app "OpenClaw"' 2>/dev/null || true
# Docker (webhook-worker has a restart policy — stop kills it for good once rm'd)
docker stop openclaw-mission-control-webhook-worker-1
launchctl list | grep -E "openclaw|openhermes|com\.milo\." | grep -v com.apple   # empty
lsof -i :18789 -i :18790                                                          # empty
pgrep -fl "OpenClaw|openclaw|Sparkle"                                             # empty
```

Remove OpenClaw from System Settings → Login Items if present.

### Step 2 — Archive (services now quiet; 3.8G source, MiloCache has 1.7Ti)

```bash
mkdir -p /Volumes/MiloCache/archives
tar -czf /Volumes/MiloCache/archives/openclaw-final-$(date +%Y%m%d).tar.gz \
  /Volumes/BotCentral/Users/milo/.openclaw
chmod 600 /Volumes/MiloCache/archives/openclaw-final-*.tar.gz    # contains secrets.json
# Mission Control DB volume:
docker run --rm -v openclaw-mission-control_postgres_data:/data:ro \
  -v /Volumes/MiloCache/archives:/out alpine \
  tar -czf /out/openclaw-mc-postgres-$(date +%Y%m%d).tar.gz -C /data .
chmod 600 /Volumes/MiloCache/archives/openclaw-mc-postgres-*.tar.gz
ls -lh /Volumes/MiloCache/archives/
```

(Until the Phase 6 gate, `.openclaw-retired` on BotCentral is the live second copy —
two copies on two volumes without extra work.)

### Step 3 — Extract migration assets (real paths)

```bash
OC=/Volumes/BotCentral/Users/milo/.openclaw
mkdir -p ~/migration-assets
cp "$OC/workspace/MEMORY.md" "$OC/workspace/USER.md" ~/migration-assets/
cp "$OC/workspace/SOUL.md" "$OC/workspace/IDENTITY.md" \
   "$OC/workspace/GotchaFramework.md" "$OC/workspace/TOOLS.md" \
   "$OC/workspace/DREAMS.md" "$OC/workspace/HEARTBEAT.md" ~/migration-assets/ 2>/dev/null
cp -r "$OC/workspace/memory" ~/migration-assets/session-notes
cp -r "$OC/workspace/agents" ~/migration-assets/agent-memories
```

No `.sqlite` files — they're derived embedding/FTS indexes, not source data.
(`hermes claw migrate` in Stream C reads from `.openclaw` directly; this copy is the
human-readable belt-and-braces set.)

### Step 4 — Remove containers, app, npm package

```bash
docker rm openclaw-mission-control-frontend-1 openclaw-mission-control-backend-1 \
  openclaw-mission-control-webhook-worker-1 openclaw-mission-control-db-1 \
  openclaw-mission-control-redis-1
# Volume openclaw-mission-control_postgres_data stays until the Phase 6 gate.
npm uninstall -g openclaw
mv /Applications/OpenClaw.app ~/.Trash/

# Remove legacy sync cron that can recreate ~/.openclaw/sync.log every 15 minutes.
crontab -l > /Volumes/MiloCache/archives/openclaw-crontab-before-$(date +%Y%m%d).txt 2>/dev/null || true
tmp=$(mktemp /tmp/hermes-crontab.XXXXXX)
crontab -l 2>/dev/null | grep -v '/Volumes/BotCentral/Users/milo/GitHub/MiloTheAssistant-Milo/tools/gh-sync.sh' > "$tmp" || true
crontab "$tmp"
rm -f "$tmp"

# Archive then remove OpenClaw's macOS support data:
tar -czf /Volumes/MiloCache/archives/openclaw-macos-support-$(date +%Y%m%d).tar.gz \
  "$HOME/Library/Application Support/OpenClaw" \
  "$HOME/Library/WebKit/ai.openclaw.mac" \
  "$HOME/Library/HTTPStorages/ai.openclaw.mac" \
  "$HOME/Library/Logs/OpenClaw" \
  "$HOME/Library/Caches/ai.openclaw.mac" \
  "$HOME/Library/Preferences/ai.openclaw.mac.plist" \
  "$HOME/Library/Preferences/ai.openclaw.shared.plist"
chmod 600 /Volumes/MiloCache/archives/openclaw-macos-support-*.tar.gz
rm -rf "$HOME/Library/Application Support/OpenClaw" \
  "$HOME/Library/WebKit/ai.openclaw.mac" \
  "$HOME/Library/HTTPStorages/ai.openclaw.mac" \
  "$HOME/Library/Logs/OpenClaw" \
  "$HOME/Library/Caches/ai.openclaw.mac" \
  "$HOME/Library/Preferences/ai.openclaw.mac.plist" \
  "$HOME/Library/Preferences/ai.openclaw.shared.plist"
```

### Step 5 — Quarantine OpenHermes (decision locked: quarantine)

```bash
mkdir -p /Volumes/MiloCache/quarantine/openhermes
mv /Volumes/BotCentral/Users/milo/Library/LaunchAgents/com.openhermes.milo.plist \
   /Volumes/MiloCache/quarantine/openhermes/
tar -czf /Volumes/MiloCache/quarantine/openhermes/dot-openhermes-$(date +%Y%m%d).tar.gz \
  /Volumes/BotCentral/Users/milo/.openhermes
tar -czf /Volumes/MiloCache/quarantine/openhermes/repos-OpenHermes-$(date +%Y%m%d).tar.gz \
  /Volumes/BotCentral/Users/milo/repos/OpenHermes
chmod 600 /Volumes/MiloCache/quarantine/openhermes/*.tar.gz
```

The `.openhermes` and `repos/OpenHermes` directories themselves stay in place,
inert (no LaunchAgent). Delete only on a later explicit decision from John.

### Step 6 — Retire `.openclaw`, delete the OpenClaw plists

```bash
# IMPORTANT: only after Stream C's claw migrate has APPLIED successfully —
# the migrate tool reads from this directory. If C hasn't run yet, defer this step.
mv /Volumes/BotCentral/Users/milo/.openclaw /Volumes/BotCentral/Users/milo/.openclaw-retired

cd /Users/milo/Library/LaunchAgents
rm -v ai.openclaw.gateway.plist ai.openclaw.smart-memory.plist com.milo.smart-memory.plist
cd /Volumes/BotCentral/Users/milo/Library/LaunchAgents
rm -v ai.openclaw.gateway.plist ai.openclaw.node.plist com.openclaw.sync-decisions.plist
```

**Stream A complete when:** ports 18789/18790 empty; no openclaw/openhermes labels in
`launchctl list`; no openclaw containers in `docker ps -a`; archives readable on
MiloCache; `~/migration-assets/MEMORY.md` exists.

-----

## Stream C — Memory Migration (first-party tool + curation)

### Step 1 — Dry run (OpenClaw stopped, Hermes updated — both prerequisites)

```bash
hermes claw migrate --dry-run \
  --preset user-data \
  --source /Volumes/BotCentral/Users/milo/.openclaw \
  --skill-conflict rename
```

**Never pass `--workspace-target`** (decision locked: OpenClaw workspace instructions
are not migrated — verified the tool skips that category cleanly when the flag is
absent). **Never pass `--migrate-secrets`** — it would import the old pre-rotation
Discord token; rotated credentials enter only via `hermes gateway setup`.

Review the plan output: what lands in Hermes memories (MEMORY.md/USER.md entries),
SOUL/persona, command allowlist merges, skill imports (`~/.hermes/skills/openclaw-imports/`).
Compare `--preset full` in a second dry run; pick deliberately.

⚠ Watch the **`model-config`** line in the dry run: this category writes OpenClaw's
old default model into Hermes's `config.yaml` — it WILL clobber Stream B's
ollama-cloud/minimax-m3 wiring when applied. Expected and handled in Step 2.
Also watch **`agent-config`**: under `--preset user-data` it may still write
`agent/compression/terminal` settings. This can undo the Stream B terminal backend or
compression choices even when `model-config` is skipped as a conflict.

### Step 2 — Apply

Current v0.16 behavior: if the dry run reports any conflicts, the migrator refuses to
apply unless `--overwrite` is supplied. Before using `--overwrite`, take an explicit
Hermes backup and then immediately re-check model/provider/terminal settings.

```bash
hermes backup -o /Volumes/MiloCache/archives/hermes-pre-openclaw-migrate-$(date +%Y%m%d-%H%M%S).zip
hermes claw migrate \
  --preset user-data \
  --source /Volumes/BotCentral/Users/milo/.openclaw \
  --skill-conflict rename \
  --overwrite \
  --yes
```

(The tool snapshots `~/.hermes` to a zip automatically before applying — keep that.)

Immediately re-verify the primary model survived the `model-config` import:

```bash
hermes config show | grep -i -E "provider|model"
hermes config show | grep -i -E "terminal|compression|auxiliary" -A 20
# If the OpenClaw default model clobbered it: re-wire with `hermes model`
# (pick minimax-m3 / ollama-cloud again), then re-confirm.
# If terminal/compression/auxiliary were clobbered: restore the Stream B choices
# before continuing.
```

### Step 3 — Curate what the tool imported

Hermes's persistent memory limits: MEMORY.md 2200 chars, USER.md 1375 chars. Legacy
files fit (1.7K / 528B) but arrive with OpenClaw-isms. In a `hermes` session (John
drives), review and prune: drop agent-roster mechanics, port 18789, ELON dispatch
rules; keep environment invariants (BotCentral lowercase-milo, plist gotchas,
MiloCache backups), preferences, project context. Verify in a **fresh** session:
"What do you know about my home directory setup?" — recalled unprompted.

### Step 4 — Park the full legacy corpus

```bash
mkdir -p ~/.hermes/legacy-openclaw
cp -r ~/migration-assets/* ~/.hermes/legacy-openclaw/
```

Validation: ask Hermes to read and summarize `legacy-openclaw/MEMORY.md` (also proves
the file toolset reaches it under the chosen exec backend). No qmd, no vector DB.

### Step 5 — Memory provider: hold the line

Built-in memory first. Only after a demonstrated recall gap in real use, evaluate
`hermes memory setup hindsight` (also: honcho, mem0, openviking).

-----

## Stream D — Gateway + Channels

### Step 1 — Precondition gate

John confirms: Telegram + Discord tokens rotated. Old credentials never enter Hermes.

### Step 2 — Gateway setup (interactive — John drives)

```bash
hermes gateway setup
```

Telegram first (primary EA channel), Discord second. New tokens only.

### Step 3 — Foreground smoke test

```bash
hermes gateway          # from phone: "ping" via Telegram → reply → Ctrl-C
```

### Step 4 — Service install (let Hermes own it)

```bash
hermes gateway install
hermes gateway status
```

Plist lands at `/Volumes/BotCentral/Users/milo/Library/LaunchAgents/ai.hermes.gateway.plist`
(derived from account home — expected). Verified in source: it bakes absolute
`HERMES_HOME`, captured full `PATH`, `VIRTUAL_ENV`, `KeepAlive`, `RunAtLoad`.

### Step 5 — Inspect, don't patch

```bash
plutil -p /Volumes/BotCentral/Users/milo/Library/LaunchAgents/ai.hermes.gateway.plist
launchctl list | grep ai.hermes
```

Confirm `HERMES_HOME` is the absolute BotCentral path; `PATH` covers `hermes`, `uv`,
`node`. **Do not hand-edit** — Hermes rewrites the plist on drift.

### Step 6 — Channel pipe validation

```bash
hermes send --list
hermes send --list telegram
hermes config set TELEGRAM_HOME_CHANNEL <telegram_chat_id>  # or send /sethome from the target Telegram chat
echo "gateway service live — $(date)" | hermes send --to telegram
```

Current live check, 2026-06-14 14:15 CDT: Telegram user `Milo` is approved in the
pairing store, `TELEGRAM_HOME_CHANNEL` is set for the DM chat, and
`hermes send --to telegram` succeeded.

### Step 7 — Plan B (only if the Phase 6 reboot test fails)

1. `launchctl bootout gui/$(id -u)/ai.hermes.gateway`; delete Hermes's plist.
2. Hand-author `/Users/milo/Library/LaunchAgents/com.milo.hermes-gateway.plist`
   (system drive, distinct label, ProgramArguments/EnvironmentVariables copied from
   the Hermes-generated plist).
3. Never run `hermes gateway install` again (it would recreate its plist → duplicate
   gateways). Manage via `launchctl` only; re-sync the plist manually after Hermes
   upgrades.

Strictly the fallback — do not pre-implement.

-----

## Stream E — EA Capabilities

### Step 1 — Kanban

```bash
hermes kanban init
hermes kanban create "Validate Hermes migration end-to-end" --assignee hermes
hermes kanban list && hermes kanban stats
```

(HermesCodex deferred kanban pending command-surface confirmation — surface verified
against current upstream: `init`/`create --assignee`/`list`/`stats` all real.)

### Step 2 — Scheduled automations (agent-native tasks only)

In a `hermes` session, one at a time, confirming each registers:

> Create a scheduled automation: every morning at 7:00 send me a briefing on
> Telegram — today's calendar, open kanban tasks, and anything overdue.

> Create a scheduled automation: every Sunday at 09:00 run a system audit — disk
> usage on BotCentral and MiloCache, docker container health, gateway launchd
> status — and send the report to Telegram.

The nightly backup is deliberately NOT an agent automation — Step 3. If an instruction
fails to register, capture Hermes's exact response, adapt phrasing, document.

### Step 3 — Nightly backups (host-level, survives agent failure)

```bash
mkdir -p /Volumes/MiloCache/backups/hermes
cat > /Users/milo/Library/LaunchAgents/com.milo.hermes-backup.plist <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.milo.hermes-backup</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-c</string>
    <string>/Volumes/BotCentral/Users/milo/.local/bin/hermes backup -o /Volumes/MiloCache/backups/hermes/hermes-$(date +%Y%m%d).zip &amp;&amp; ls -t /Volumes/MiloCache/backups/hermes/hermes-*.zip | tail -n +15 | xargs rm -f --</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key><string>/Volumes/BotCentral/Users/milo</string>
    <key>PATH</key><string>/Volumes/BotCentral/Users/milo/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>2</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>/Volumes/MiloCache/backups/hermes/backup.log</string>
  <key>StandardErrorPath</key><string>/Volumes/MiloCache/backups/hermes/backup.err.log</string>
</dict>
</plist>
EOF
plutil -lint /Users/milo/Library/LaunchAgents/com.milo.hermes-backup.plist
launchctl bootstrap gui/$(id -u) /Users/milo/Library/LaunchAgents/com.milo.hermes-backup.plist
launchctl kickstart gui/$(id -u)/com.milo.hermes-backup    # fire once now
ls -lh /Volumes/MiloCache/backups/hermes/
```

(The `~/.local/bin/hermes` symlink was created in Stream B Step 3. Retention: 14.)

### Step 4 — Skills seeding (self-awareness)

Walk each recurring workflow once in a `hermes` session, then:

> Write a reusable skill documenting what we just did, including the exact commands
> and the gotchas we hit.

Seed list: (1) GitHub API push/fetch pattern; (2) the launchd plist pattern on this
dual-volume machine; (3) morning briefing format; (4) backup verify + restore drill.
Review what `claw migrate` already imported into `~/.hermes/skills/openclaw-imports/`
before writing duplicates. Then `hermes skills` — install only what maps to real
workflows.

### Step 5 — MCP servers

```bash
hermes mcp list
hermes mcp add <name> ...     # only with a concrete near-term use
hermes mcp test <name>
```

Each MCP server adds tools to every prompt — drag. Add on demand, prune with
`hermes mcp remove`.

### Step 6 — Observability (built-in, zero containers)

```bash
hermes dashboard       # 127.0.0.1:9119 — config, keys, sessions
hermes status
```

Keep it localhost-bound. Langfuse only on demonstrated need — Cloud or the bundled
plugin, never the six-container self-host.

### Step 7 — Persistent goal

```
/goal Complete X.com Developer API setup: app registered, OAuth keys stored in .env, a test post sent from this machine, and a skill written documenting the flow.
```

-----

## Phase 6 Gate — run after C, D, E all complete

```bash
# 1. Services survive reboot (John performs reboot + login)
sudo reboot
# after login:
/Volumes/BotCentral/Users/milo/bin/hermes-phase6-gate.sh       # non-destructive summary gate
launchctl list | grep ai.hermes                          # gateway running
launchctl list | grep com.milo.hermes-backup             # backup job loaded
crontab -l 2>/dev/null | grep -i openclaw                # nothing
docker ps -a | grep openclaw                             # nothing
docker info --format '{{.OperatingSystem}}'              # OrbStack up
lsof -i :11434 -P | grep LISTEN                          # normally no listener; never *:11434

# 2. Channel round-trip
echo "post-reboot check $(date)" | hermes send --to telegram

# 3. Memory persistence (fresh session)
hermes    # "What do you know about my home directory setup?" → recalled unprompted

# 4. Backup fired
ls -lh /Volumes/MiloCache/backups/hermes/                # zip present, log clean

# 5. Tools + research end-to-end
hermes    # "Find one AI news item from this week using web search, summarize it,
          #  and save the summary to a file."

# 6. Kanban alive
hermes kanban stats
```

**All six pass in one pass:**

```bash
/Volumes/BotCentral/Users/milo/bin/hermes-phase6-finalize.sh --yes
docker image prune    # review list; remove openclaw-mission-control images
# Keep permanently: /Volumes/MiloCache/archives/*, /Volumes/MiloCache/quarantine/*,
# ~/migration-assets/. OpenHermes stays quarantined pending John's later decision.
```

Execution note (2026-06-14): Phase 6 passed after reboot, the guarded finalizer
removed `.openclaw-retired` and `openclaw-mission-control_postgres_data`, and
the OpenClaw Mission Control images were removed. Finalizer logs:
`/Volumes/MiloCache/archives/hermes-phase6-finalize-20260614-112619`.

Reboot check fails on the gateway → Stream D Step 7 Plan B, re-run the gate.

-----

## Notes for Claude Code

- Lowercase `milo`; verify `/Volumes/BotCentral/Users/milo/` AND `/Volumes/MiloCache/`
  resolve before every stream.
- Never echo, log, or commit API keys or tokens. Wizards or `~/.hermes/.env`
  (`chmod 600`) only. Never pass `--migrate-secrets` to `claw migrate`.
- Exact launchd labels only — broad greps match Apple services (`milod`,
  `askpermissiond`, `ThreadCommissionerService`).
- Interactive steps (wizards, OAuth, hermes-session instructions) pause and hand to
  John. Do not simulate his side.
- Do not hand-edit `ai.hermes.gateway.plist`. The only hand-managed plists are
  `com.milo.hermes-backup` (and `com.milo.hermes-gateway` if Plan B ever activates).
- Ordering is load-bearing: B before C; A-decommission stop/archive before C applies;
  `.openclaw` → `.openclaw-retired` rename only AFTER `claw migrate` has applied.
- Do not delete `.openclaw-retired`, the MiloCache archives, or the postgres volume
  unless all six gate checks pass in one pass.
- Everything network-facing stays on 127.0.0.1: local Ollama if it is re-enabled,
  `hermes dashboard`, any future service. If any step suggests 0.0.0.0, refuse.
- If a `hermes` command's syntax disagrees with this brief, trust `hermes <cmd> --help`
  (post-update build) over the brief, and note the discrepancy.

---
name: vercel-gh-deploy-doctrine
description: "Use when shipping code through GitHub + Vercel — preview before prod, scoped PRs, secret-safe."
version: 1.0.0
author: Hermes Agent + Milo
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [vercel, github, deploy, pr, ci, devops, doctrine]
    related_skills: [github-pr-workflow, github-repo-management, github-auth, github-code-review]
---

# Vercel + GitHub Deploy Doctrine

The deploy loop is one workflow, not two. Treat Vercel as deployable
infrastructure, GitHub as the audit trail, and prove each stage before
moving to the next. Skip a stage and you debug it later under pressure.

## When to Use

- Opening a PR that will deploy (most feature work in this repo)
- Deploying a Vercel preview or production build from a branch
- Anything that mentions `vercel`, `vercel.json`, or a `.vercel/` directory
- After a CI failure you suspect came from preview/prod env divergence
- Resuming a deploy that was halted by a 3-minute cron interrupt (see Pitfalls)

## When NOT to Use

- Pure local edits with no deploy surface → use plain `terminal` + `write_file`
- GitHub-only work (issues, code review without deploy) → use `github-pr-workflow` + `github-code-review`
- Non-Vercel targets (Fly, Render, Cloudflare Pages, self-hosted) → the Vercel
  specifics don't apply; use a target-specific skill instead

## The Loop (5 stages)

```
prove state → branch+commit → PR (draft) → preview → production
                                  ↑           │
                                  └───────────┘  (preview verify gates prod)
```

Each stage has a checkable completion criterion. Don't move on until the
criterion is green.

---

## 1. Prove State (before anything)

Run these four probes. If any fails, stop and report the exact failure —
do not invent a workaround.

```bash
git status --short --branch          # branch + unrelated local changes
gh auth status 2>&1 | head -3        # GH CLI authenticated?
vercel whoami 2>&1 | head -3         # Vercel CLI authenticated?
ls -la .vercel/ 2>/dev/null          # project linkage present?
```

Completion: you can name the branch, the GH user, the Vercel user/org,
and the linked project name. If any name is missing, the workflow
cannot proceed.

---

## 2. Branch + Commit (scoped, focused)

- Branch name carries the intent: `feat/...`, `fix/...`, `refactor/...`,
  `docs/...`, `ci/...`, `skill/...`. Never commit to `main` directly.
- One concern per branch. If `git status --short` shows unrelated changes,
  stash them (`git stash -u -- <path>`) or split into a separate branch.
- Commits are small and auditable. Imperative subject, focused body. No
  "wip", no "fix typo" stacked with feature work.

```bash
git fetch origin
git checkout main && git pull --ff-only origin main
git checkout -b feat/<short-description>
# ... edits via write_file / patch ...
git add -p                            # stage hunks, review each one
git commit -m "feat(scope): <imperative summary>"
git push -u origin HEAD
```

Completion: `git log --oneline origin/main..HEAD` shows your commits,
and `git status --short` is empty (unrelated changes stashed or split).

---

## 3. PR (draft, not ready)

Open the PR **as draft** whenever the work needs review, CI validation,
or a preview to verify. Title mirrors the branch. Body must include:

- **Summary** — what changed and why (1–3 sentences)
- **Verification** — what you ran, what passed
- **Risks** — what could break, what you did not test
- **Follow-up** — known TODOs, deferred work, or "none"

```bash
gh pr create --draft \
  --title "feat(scope): <title>" \
  --body "$(cat <<'EOF'
## Summary
<1–3 sentences>

## Verification
- [ ] <command> → <expected result>
- [ ] <command> → <expected result>

## Risks
- <what could break>

## Follow-up
- <known TODO or 'none'>
EOF
)"
```

Mark ready for review only after preview deploys and verification runs
green. Use `gh pr view`, `gh pr status`, and `gh pr checks` to inspect
state — never guess from branch name alone.

Completion: draft PR exists, body has all four sections, CI is running.

---

## 4. Preview (HTTP + log verified, not built)

A green build is not a working preview. Vercel previews must be
**HTTP-verified** with logs inspected before declaring success.

```bash
# After Vercel bot comments the preview URL on the PR
PREVIEW_URL=$(gh pr view --json comments \
  | jq -r '.comments[] | select(.author.login | test("vercel"; "i")) | .body' \
  | grep -oE 'https://[^ ]+' | head -1)

# HTTP verify
curl -sS -o /dev/null -w "status=%{http_code} time=%{time_total}s\n" "$PREVIEW_URL"

# Inspect the preview's runtime logs (NOT prod logs)
vercel logs "$PREVIEW_URL" --since 5m
```

**Preview vs. production env vars are separate.** A common bug: a key
that exists in preview (e.g. test Stripe key) does not exist in prod
(real Stripe key) — or vice versa. Always confirm env values per env:

```bash
vercel env ls production
vercel env ls preview
vercel env ls development
```

Protected preview deployments: the bypass mechanism (e.g.
`VERCEL_AUTOMATION_BYPASS_SECRET`) must come from an **environment
variable**, never inlined into a script, command, or PR body.

Completion: preview URL returns 2xx, logs show no errors, and the
required env vars exist for the preview environment.

---

## 5. Production (only after preview is green)

```bash
vercel deploy --prod --yes
```

Confirm via HTTP + logs the same way you did for preview:

```bash
PROD_URL=$(vercel inspect --prod --json | jq -r '.url')
curl -sS -o /dev/null -w "status=%{http_code} time=%{time_total}s\n" "$PROD_URL"
vercel logs "$PROD_URL" --since 1m
```

If the user explicitly asked for production directly (and preview-first
is not required), you may skip stage 4 — but you must still HTTP-verify
+ log-inspect prod after deploy. Never trust "deployment succeeded"
without a live HTTP probe.

Completion: production URL returns 2xx, no errors in logs, env vars
match preview's intent (where applicable), URL + verification result
reported to the user.

---

## Quick Reference: Common Commands

| Task | Command |
|------|---------|
| Check GH auth | `gh auth status` |
| Check Vercel auth | `vercel whoami` |
| Link project | `vercel link` |
| List env (env = dev/preview/prod) | `vercel env ls <env>` |
| Add env var | `vercel env add <NAME> <env>` |
| Deploy preview | `vercel deploy` (auto on PR push) |
| Deploy production | `vercel deploy --prod --yes` |
| Get prod URL | `vercel inspect --prod --json \| jq -r '.url'` |
| Tail logs | `vercel logs <url> --since <duration>` |
| Inspect PR | `gh pr view <num>` |
| PR checks | `gh pr checks <num>` |
| Open draft PR | `gh pr create --draft --title ... --body ...` |
| Mark PR ready | `gh pr ready <num>` |

---

## Common Pitfalls

1. **Cron 3-minute hard interrupt kills prod deploys mid-flight.** The
   `brief-*` cron jobs in this repo push git synchronously, then detach
   `vercel deploy --prod --yes` with `nohup ... &` so it survives the
   cron turn. Pattern:
   ```bash
   nohup bash -c 'cd <repo> && npm run fetch-briefs && vercel deploy --prod --yes' \
     > /tmp/<job>-deploy.log 2>&1 &
   ```
   Do **not** run prod deploy inline from a cron job — the cron turn
   will be killed before deploy finishes, leaving a half-applied state.

2. **Preview/prod env vars are independent.** Adding `STRIPE_KEY` to
   preview does not add it to prod. Always run `vercel env ls <env>`
   for each environment before relying on a value being present.

3. **"Build succeeded" ≠ "site works".** A 200 from Vercel's build
   status only means the bundle compiled. Always do an HTTP probe
   (`curl -I` or `-w "%{http_code}"`) against the deployed URL and
   inspect runtime logs. Catches: missing env, wrong runtime, broken
   rewrites, broken API routes.

4. **Squash-merge from a stale branch silently reverts recent fixes.**
   Before squash-merging a PR, rebase it onto current `main`
   (`git fetch origin main && git rebase origin/main`) and
   `git diff HEAD~1..HEAD` to confirm the diff is what you expect.

5. **Committing unrelated changes.** If `git status --short` shows
   modifications outside the PR's scope, either split into a separate
   branch or stash (`git stash -u -- <path>`). The deploy-PR must
   contain one concern, otherwise rollback is impossible without
   ripping out unrelated fixes.

6. **Inline bypass secrets.** `VERCEL_AUTOMATION_BYPASS_SECRET` and
   similar must come from the environment, never from a literal in a
   script, command, log, or PR body. Redact by replacing with
   `<bypass-from-env>` in any text the user could see.

7. **Trusting `gh pr view`'s summary alone.** Use `gh pr status` for
   merge readiness, `gh pr checks` for CI detail, and `gh pr view
   --comments` to see the Vercel bot's preview URL. Each surfaces
   different state.

8. **No rollback plan.** Before deploying prod, know how you'd roll
   back: `vercel rollback` to the previous deployment, or
   `git revert` + new PR. State the rollback plan in the PR's Risks
   section if the change is non-trivial.

9. **Mixing env secrets into `.env.example`.** `.env.example` is
   committed; `.env` is not. Never put real values in the example.
   For Vercel, secrets live in `vercel env add` and are injected at
   build/runtime — they should not be in any committed file.

---

## Handoff Template

After every deploy, report (one paragraph, plain prose):

- **Branch / PR:** `<branch>` → PR #`<num>` (state: draft | ready | merged)
- **Preview:** `<url>` — `curl` returned `<code>` in `<time>s`; logs clean
- **Production:** `<url>` — `curl` returned `<code>` in `<time>s`; logs clean
- **Verified:** `<what you exercised end-to-end>`
- **Risks:** `<what you did NOT test, or 'none'>`
- **Follow-up:** `<known TODOs, or 'none'>`

This is the same shape as a PR body — keeping the loop symmetric
makes "what shipped?" answerable from one place.

---

## Verification Checklist

- [ ] Stage 1: `git status --short --branch`, `gh auth status`, `vercel whoami`, `.vercel/` presence all reported
- [ ] Stage 2: branch name carries intent; commits are scoped; unrelated changes stashed
- [ ] Stage 3: draft PR exists with Summary / Verification / Risks / Follow-up
- [ ] Stage 4: preview URL HTTP-verified (2xx); logs inspected; preview env vars present
- [ ] Stage 5: prod URL HTTP-verified (2xx); logs inspected; rollback plan known
- [ ] Handoff report covers Branch / Preview / Production / Verified / Risks / Follow-up
- [ ] No secrets inlined in commands, logs, PR body, or chat reply
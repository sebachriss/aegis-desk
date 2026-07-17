# Devin Integration for Aegis Desk

This directory contains Devin-specific configuration, custom subagents, playbooks, and workflows for the Aegis Desk project.

## Quick reference

- **Project instructions**: see `AGENTS.md` in the repo root.
- **Frontend rules**: see `frontend/AGENTS.md`.
- **Module rules**: see `evals/AGENTS.md`, `redteam/AGENTS.md`, and `src/security/AGENTS.md`.

## Custom subagents

Subagent configs live in `.devin/agents/<name>/AGENT.md`.

| Subagent | Purpose |
|----------|----------|
| `reviewer` | Code review focused on correctness, security, RBAC, evals, and style. |
| `test-runner` | Runs tests, evals, and redteam reports. |
| `researcher` | Explores architecture and reports back with file/line references. |
| `security-auditor` | Audits for red-team style vulnerabilities and defense-in-depth gaps. |
| `frontend-coder` | Next.js 16 / React 19 / Tailwind 4 / shadcn/ui development. |
| `eval-engineer` | Maintains `evals/` datasets, metrics, and regression tests. |

## Playbooks

Reusable prompt templates for common tasks:

- `playbooks/add-worker.md` — add a new LangGraph worker.
- `playbooks/fix-eval-regression.md` — fix a failing eval case.

## Workflows

Step-by-step workflows for multi-step tasks (can include `// turbo` auto-run steps):

- `workflows/add-worker.md`
- `workflows/fix-eval-regression.md`
- `workflows/security-audit.md`

## Usage in Devin

1. Start from the project root so Devin reads `AGENTS.md` automatically.
2. Call subagents by name for specialized work, e.g.:
   - `Run @test-runner to verify this change`
   - `Ask @security-auditor to review this PR`
   - `Assign @frontend-coder to add a settings page`
3. Use workflows for repetitive multi-step tasks by saying `Run the add-worker workflow`.
4. Keep results in `evals/results/` and `redteam/results/`; do not commit API keys or traces.
5. For Supabase/Postgres work, ensure `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_KEY` and `SUPABASE_SERVICE_KEY` are in `.env` before running migrations.

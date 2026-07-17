# Red Team — Agent Instructions

This directory contains red teaming payloads and runners for Aegis Desk.

- `run_redteam.py` runs attack payloads and checks defense-in-depth layers.
- `attacks/payloads.json` holds prompt injection, jailbreak, RBAC bypass, SQL injection, data exfiltration, and tool abuse payloads.

## Conventions

- Categorize payloads by `category`: `prompt_injection_direct`, `prompt_injection_indirect`, `rbac_bypass`, `sql_injection`, `data_exfiltration`, `tool_abuse`.
- Each payload must define `expected_behavior` (e.g., `blocked`, `hitl`, `refused`, `allowed`).
- Keep payloads realistic for an internal support chatbot scenario.
- Do not include real credentials, PII, or production secrets.
- Attacks that target Supabase/Postgres should assume `DATABASE_URL` is configured.

## Before committing

```bash
python -m redteam.run_redteam --save
```

If the defense rate drops, involve the `security-auditor` subagent and update guardrails in `src/security/`.

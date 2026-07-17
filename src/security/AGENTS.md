# Security — Agent Instructions

This directory contains the security guardrails for Aegis Desk.

- `prompt_injection.py` detects injection patterns in user input and can sanitize RAG documents.
- `rbac.py` defines roles (`empleado`, `admin`) and maps allowed tools/intentions.
- `rate_limiter.py` is an in-memory sliding-window rate limiter (10 requests / 120s per user).
- `pii_filter.py` masks emails, phones, DNIs, and sensitive key-value pairs in text.

## Conventions

- Prefer deterministic code checks over LLM-based prompts for guardrails.
- Any change that adds or removes a tool/intention must update `rbac.py`.
- Any change that touches security must be reflected in `redteam/attacks/payloads.json`.
- Do not log secrets or PII; apply `filter_pii()` before storing traces or returning responses.
- Supabase credentials (`SUPABASE_SERVICE_KEY`, `DATABASE_URL`) are injected via `.env` and must never appear in code or traces.

## Before committing

```bash
python scripts/test_security.py
python -m redteam.run_redteam --save
```

For a deeper review, invoke the `security-auditor` subagent.

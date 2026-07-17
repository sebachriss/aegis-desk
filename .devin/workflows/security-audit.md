---
description: Audit a change or module for security issues
---
# Workflow: Security audit for Aegis Desk

## Goal
Verify that a code change, new tool, or new worker does not introduce security vulnerabilities.

## Steps

// turbo
1. Run `git diff` to identify changed files and save the diff.
2. Read the diff and list affected workers, tools, endpoints, prompts, or RAG documents.
3. Read `src/security/rbac.py` and any affected `src/tools/*.py` and `src/agents/*.py`.
4. Check for these categories of risk:
   - RBAC bypass (tools exposed to the wrong role)
   - SQL injection or schema leakage
   - Prompt injection / RAG poisoning
   - PII leakage in responses, traces, or logs
   - Rate limit / auth bypass
   - HITL bypass or side effects before approval
   - CORS / JWT / secret issues
// turbo
5. Run `python scripts/test_security.py` if it exists.
// turbo
6. Run a focused red team pass: `python -m redteam.run_redteam --save` or `python -m redteam.run_redteam --category <category>`.
7. Write findings to `.devin/reports/security_audit_<timestamp>.md` or as comments on the PR.
8. Do not close the audit until all P0 findings are triaged.

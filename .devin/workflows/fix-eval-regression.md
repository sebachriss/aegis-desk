---
description: Fix a regression detected by the evaluation suite
---
# Workflow: Fix an eval regression in Aegis Desk

## Goal
A case in `evals/datasets/test_cases.json` is failing. Find the root cause, apply the smallest upstream fix, and restore the baseline.

## Steps

// turbo
1. Run `python -m evals.run_evals --save` and identify the failing case(s).
2. Reproduce the failing case manually with `python scripts/cli_chat.py` or a minimal script.
3. Read the relevant worker (`src/agents/<worker>_agent.py`), `src/agents/supervisor.py`, and `src/agents/graph.py`.
4. Diagnose the root cause: prompt, routing, `AgentState` fields, tool behavior, or test data.
5. Apply the smallest upstream fix; avoid workarounds unless strictly necessary.
// turbo
6. Run the focused phase test (`python scripts/test_<phase>.py`).
// turbo
7. Run `python -m evals.run_evals --save` again.
// turbo
8. If the fix touches security, run `python -m redteam.run_redteam --save`.
9. Update docs or playbooks if the failure reveals a systemic pattern.

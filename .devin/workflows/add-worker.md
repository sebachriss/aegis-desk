---
description: Add a new LangGraph worker to Aegis Desk
---
# Workflow: Add a new worker to Aegis Desk

## Goal
Add a new worker node to the multi-agent LangGraph and wire it into the supervisor, RBAC, tools, tests, and evals.

## Steps

1. Read `src/agents/state.py` and decide whether `AgentState` needs new fields.
2. Create `src/agents/<name>_agent.py` with a function `<name>_node(state: AgentState) -> dict`.
3. Update `src/agents/supervisor.py` so the supervisor can route to the new intention.
4. Add the node and conditional edges in `src/agents/graph.py`.
5. If the worker needs tools, register them in `src/tools/registry.py` and permissions in `src/security/rbac.py`.
6. Create `scripts/test_<name>_agent.py` with at least three deterministic cases.
7. Add representative cases to `evals/datasets/test_cases.json`.
// turbo
8. Run `python scripts/test_<name>_agent.py`.
// turbo
9. Run `python scripts/test_multi_agent.py`.
// turbo
10. Run `python -m evals.run_evals --save`.
// turbo
11. Run `python -m redteam.run_redteam --save`.
12. Update `AGENTS.md` and any relevant playbook/workflow with the new worker.

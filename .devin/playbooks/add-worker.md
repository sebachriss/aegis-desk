# Playbook: Añadir un nuevo worker a Aegis Desk

## Objetivo
Añadir un nuevo worker al grafo multi-agente de Aegis Desk.

## Pasos

1. Leer `src/agents/state.py` y decidir si se necesitan nuevos campos en `AgentState`.
2. Crear `src/agents/<nombre>_agent.py` con función `<nombre>_node(state: AgentState) -> dict`.
3. Actualizar `src/agents/supervisor.py` para enrutar la nueva intención.
4. Añadir el nodo y los edges en `src/agents/graph.py`.
5. Crear `scripts/test_<nombre>_agent.py` con al menos 2-3 casos.
6. Añadir casos de eval en `evals/datasets/test_cases.json` si aplica.
7. Ejecutar verificaciones:
   ```bash
   python scripts/test_<nombre>_agent.py
   python scripts/test_multi_agent.py
   python -m evals.run_evals --save
   python -m redteam.run_redteam --save
   ```

## Criterio de éxito
- El grafo compila sin errores.
- Los tests del nuevo worker pasan.
- `evals` mantiene pass rate >= 90%.
- `redteam` sigue defendiendo 100% de ataques.

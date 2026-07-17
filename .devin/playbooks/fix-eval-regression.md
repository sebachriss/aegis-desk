# Playbook: Arreglar regresión en evals

## Objetivo
Un caso de `evals/datasets/test_cases.json` falla tras un cambio. Encontrar y corregir la causa raíz con el mínimo cambio posible.

## Pasos

1. Ejecutar `python -m evals.run_evals --save` para identificar el caso fallido.
2. Reproducir manualmente con `python scripts/cli_chat.py` o un script aislado.
3. Diagnosticar la causa raíz:
   - ¿Prompt del supervisor/worker malformado?
   - ¿Routing incorrecto en `graph.py`?
   - ¿Datos de prueba obsoletos?
   - ¿Cambio en `AgentState` que rompe un nodo?
4. Aplicar el fix mínimo upstream (no workaround a menos que sea estrictamente necesario).
5. Ejecutar el test de fase correspondiente (`python scripts/test_*.py`).
6. Ejecutar `python -m evals.run_evals --save` de nuevo.
7. Si el fix afecta seguridad, ejecutar `python -m redteam.run_redteam --save`.

## Criterio de éxito
- `evals` vuelve a baseline (actualmente 32/33, score 0.970).
- `redteam` sigue con 100% defense rate.

# 7. Evals y LLM-as-judge

## Concepto

Evaluar sistemas de LLM es distinto a testear software tradicional: la salida no es determinista
y "correcto" a veces es un juicio matizado (¿la respuesta es "suficientemente" correcta? ¿está
completa?). Enfoques comunes:

- **Golden datasets / test cases**: un conjunto fijo de (query, comportamiento esperado) que
  corres cada vez que cambias un prompt o modelo, para detectar regresiones — el equivalente a
  tests de integración pero para comportamiento de LLM.
- **LLM-as-judge**: usar un LLM (idealmente distinto o más capaz que el que generó la respuesta)
  para evaluar la calidad de otra respuesta según criterios explícitos, devolviendo un score y
  justificación. Es escalable (no necesitas humanos revisando cada caso) pero tiene sus propios
  riesgos: sesgo del juez, inconsistencia entre corridas, y el juez puede tener los mismos
  puntos ciegos que el modelo evaluado si es la misma familia de modelo.
- **Métricas RAG específicas (estilo RAGAS)**:
  - **Faithfulness**: ¿cada afirmación de la respuesta está respaldada por el contexto
    recuperado, o el modelo "inventó" (alucinó) algo?
  - **Answer relevance**: ¿la respuesta aborda realmente la pregunta hecha?
  - **Context precision**: ¿los chunks recuperados eran relevantes, o el retriever trajo ruido?
  RAGAS "real" usa modelos NLI (Natural Language Inference) especializados para faithfulness en
  vez de un LLM genérico como juez — más barato y consistente a escala, pero el principio
  evaluado es el mismo.

## Cómo está implementado en Aegis Desk

- **Dataset de 33 casos** en `evals/datasets/test_cases.json`, cubriendo RAG, datos, acción, chat,
  y casos adversariales — corridos con `python -m evals.run_evals --save`
  (ver <ref_file file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/evals/AGENTS.md" />).

- **`judge_response()`** en <ref_file file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/evals/judges.py" />:
  recibe `query`, `response`, y uno de tres tipos de expectativa (`expected_contains`,
  `should_block`, `should_deny`), y devuelve `EvaluacionJuez(score, razon, categoria)` con
  `categoria ∈ {correcta, parcial, incorrecta, rechazada}`. Detalle importante del prompt del
  juez: si la pregunta era un ataque y el sistema la bloqueó correctamente, eso es `score=1.0,
  categoria="rechazada"` — es decir, **bloquear correctamente también es un "acierto"**, no un
  fallo del sistema, y el juez lo sabe explícitamente porque se le dice en el prompt.

- **Métricas RAG** en <ref_file file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/evals/rag_evals.py" />:
  `evaluate_faithfulness`, `evaluate_answer_relevance`, `evaluate_context_precision`, cada una
  con su propio schema Pydantic y prompt de evaluación específico. Todas usan
  `get_llm(temperature=0)` — determinismo también en el juez, no solo en el sistema evaluado.
  `evaluate_rag()` las corre juntas y devuelve un diccionario consolidado.

- **`run_evals.py`**: corre los 33 casos contra el grafo real, calcula el score con el juez, y
  guarda un reporte en `evals/results/`. El README menciona 33/33 pasando con score 1.000 tras la
  migración al modelo híbrido — es decir, se usa como **regression test** después de cambios de
  modelo/prompt (exactamente el propósito de tener un dataset fijo).

## Preguntas de entrevista

**P: ¿Cómo evalúas la calidad de un sistema que no tiene una única "respuesta correcta"
determinista?**
> Con LLM-as-judge: le doy al juez la pregunta, la respuesta del sistema, y lo que se esperaba
> (puede ser texto que debería contener, o un comportamiento como "debería haber sido bloqueado"
> o "debería haber sido denegado por RBAC"), y el juez devuelve un score 0-1 con una categoría y
> justificación. Uso `temperature=0` en el juez para reducir variabilidad entre corridas, y un
> dataset fijo de 33 casos que corro cada vez que cambio un prompt o modelo, para detectar
> regresiones.

**P: ¿Qué riesgos tiene usar LLM-as-judge y cómo los mitigas (o qué falta mitigar)?**
> El juez puede tener sesgos sistemáticos (favorecer respuestas más largas, ser inconsistente
> entre corridas, o compartir puntos ciegos con el modelo evaluado si son de la misma familia).
> Mitigo parcialmente con `temperature=0` y un prompt de juez muy explícito sobre los criterios y
> categorías esperadas. Lo que le falta a mi implementación actual: no corro el juez varias veces
> por caso para medir varianza, y no valido el juez contra etiquetas humanas para medir su propia
> precisión — sería el siguiente paso para confiar más en la métrica a escala.

**P: Explícame faithfulness vs answer relevance vs context precision en RAG.**
> Faithfulness mide si la respuesta está respaldada por las fuentes recuperadas (detecta
> alucinación en la etapa de generación). Answer relevance mide si la respuesta aborda la
> pregunta hecha, independiente de si usa las fuentes bien o mal. Context precision mide la
> calidad del retrieval en sí: de los chunks que trajiste, ¿cuántos eran realmente relevantes?
> Son complementarias porque un sistema puede fallar en cualquiera de las dos etapas (retrieval
> o generation) de forma independiente — si context precision es baja pero faithfulness es alta,
> el problema está en el retriever, no en el LLM generando.

**P: ¿Cómo diseñarías un caso de eval para un ataque de prompt injection?**
> Con `should_block=True` en vez de `expected_contains` — le digo al juez explícitamente que la
> expectativa correcta es que la solicitud haya sido bloqueada, y que eso vale `score=1.0,
> categoria="rechazada"`, no un fallo. Esto evita el error común de tratar "el sistema se negó a
> responder" como una respuesta incompleta cuando en realidad es el comportamiento correcto y
> deseado.

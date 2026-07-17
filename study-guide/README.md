# Guía de estudio — AI Engineering (basada en Aegis Desk)

Esta guía usa tu propio proyecto (`aegis-desk`) como ancla para repasar los conceptos que
un entrevistador de AI Engineering espera que domines. Cada archivo tiene tres partes:

1. **Concepto** — la teoría, en general (no específica de tu proyecto).
2. **Implementación real** — cómo está hecho en Aegis Desk, con referencias a archivos/líneas.
3. **Preguntas de entrevista** — con una respuesta modelo que puedes adaptar y contar como historia real.

## Índice

| # | Archivo | Tema |
|---|---|---|
| 1 | [01-arquitectura-multiagente.md](01-arquitectura-multiagente.md) | Arquitectura multi-agente, LangGraph, patrones de orquestación |
| 2 | [02-rag.md](02-rag.md) | RAG: chunking, retrieval, generación, citas, RAG poisoning |
| 3 | [03-embeddings-vectorstores.md](03-embeddings-vectorstores.md) | Embeddings, similitud semántica, vector stores |
| 4 | [04-llms-prompting-structured-output.md](04-llms-prompting-structured-output.md) | LLMs, prompting, structured output, function calling, latencia/costo |
| 5 | [05-seguridad.md](05-seguridad.md) | RBAC, prompt injection, PII, rate limiting, SQL injection, defense-in-depth |
| 6 | [06-hitl.md](06-hitl.md) | Human-in-the-loop, interrupts, side effects, idempotencia |
| 7 | [07-evals-llm-as-judge.md](07-evals-llm-as-judge.md) | Evals, LLM-as-judge, métricas RAG (RAGAS-style) |
| 8 | [08-red-teaming.md](08-red-teaming.md) | Red teaming, categorías de ataque, defense-in-depth testing |
| 9 | [09-observabilidad-memoria.md](09-observabilidad-memoria.md) | Tracing, memoria conversacional, observabilidad |
| 10 | [10-fine-tuning-vs-rag-vs-prompting.md](10-fine-tuning-vs-rag-vs-prompting.md) | Fine-tuning (NO usado en el proyecto) vs RAG vs prompting — teoría para la entrevista |
| 11 | [11-preguntas-generales-entrevista.md](11-preguntas-generales-entrevista.md) | Preguntas generales de "cuéntame de un proyecto", trade-offs, decisiones de diseño |

## Cómo usar esto

- Repasa un archivo por sesión de estudio, no todos de golpe.
- Para cada pregunta de entrevista, intenta responderla en voz alta ANTES de leer la respuesta modelo.
- Si algo no lo tienes claro, abre el archivo de código referenciado y léelo de nuevo — es la mejor forma de anclar el concepto a algo concreto que tú mismo escribiste.
- Ten en cuenta: no todo lo que dice esta guía sobre "buenas prácticas en producción" está implementado al 100% en tu proyecto (es un proyecto de aprendizaje). La guía te lo señala cuando aplica, para que puedas hablar de las limitaciones con honestidad en la entrevista — eso también es una señal positiva para un entrevistador senior.

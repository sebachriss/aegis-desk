# Plan de Implementación y Auditoría — RAG Avanzado (Hybrid Search + Reranking)

> Feature: ampliar el corpus, medir baseline de retrieval (recall@k / MRR),
> implementar hybrid search (BM25 + dense con RRF) y reranking con
> cross-encoder, y mejorar citas con sección del documento.
>
> Estado: **PLANIFICADO — no ejecutado**.
> Criterio de éxito global: **mejora medida** de recall@k/MRR vs baseline,
> con los 37 evals y el redteam al 100% como anti-regresión.

## Contexto (estado actual verificado)

- Corpus: 3 documentos (~820 palabras, ~22 chunks) en `src/rag/documents/`.
- Chunking: `MarkdownHeaderTextSplitter` + `RecursiveCharacterTextSplitter(500)`.
- Retriever (`src/rag/retriever.py`): dense-only, `k=3`, `RELEVANCE_THRESHOLD=0.3`,
  backends Pinecone > Supabase pgvector > Chroma local. Ya expone
  `retrieval_scores` y `discarded` (`_SearchResult`).
- Embeddings: DeepInfra multilingüe (remoto) o MiniLM local (`src/rag/embeddings.py`).
- No existe: hybrid search, reranking, evals de retrieval.

---

## Metodología de ejecución: subagentes + auditoría entre fases

Cada fase se ejecuta con el patrón **implementar → auditar → gate**:

1. **Subagente implementador** (`subagent_general`): ejecuta SOLO la fase
   asignada, con alcance cerrado (archivos listados, criterios de aceptación
   explícitos). Prohibido tocar archivos fuera de su fase.
2. **Subagente auditor** (`subagent_explore`, read-only): revisa el diff de la
   fase contra su checklist de auditoría (abajo, por fase). Reporta:
   `APROBADO` o lista de hallazgos bloqueantes/menores.
3. **Gate del orquestador** (sesión principal): corre los comandos de
   verificación de la fase. Si el auditor reporta bloqueantes o el gate falla,
   se corrige ANTES de pasar a la siguiente fase. Commit por fase.

Reglas anti-sobreingeniería (van en el prompt de cada implementador):
- No agregar código "por si acaso": solo lo que exige el criterio de aceptación.
- No refactorizar código ajeno a la fase.
- No agregar dependencias sin justificación en el reporte (y versión con
  ≥7 días de publicada).
- Tests primero cuando la fase lo permita (TDD).

Paralelización: las fases son secuenciales por diseño (cada una depende de la
anterior), pero dentro de la Fase 1 la redacción de documentos puede repartirse
en 2 subagentes en paralelo (docs distintos, sin conflicto de archivos).

---

## Parte A — Fases de implementación

### Fase 1 — Ampliar corpus

**Subagentes:** 2 × `subagent_general` en paralelo (docs repartidos) + auditor.
**Archivos:** `src/rag/documents/*.md` (nuevos), `python -m src.rag.ingest`.

- [ ] 10–12 documentos nuevos en markdown con headers consistentes (`##` por
  sección), mismo estilo que los existentes. Temas:
  - Lote A: política de vacaciones detallada (alineada con la feature
    implementada: 22 días, días hábiles, HITL), onboarding, beneficios,
    código de conducta, teletrabajo ampliado.
  - Lote B: gastos y viáticos, seguridad de la información, uso de equipos,
    licencias médicas/especiales, evaluación de desempeño, salas de reuniones.
- [ ] Incluir deliberadamente pares de documentos con vocabulario similar
  (ej. "licencias" vs "vacaciones", "equipos" vs "seguridad de equipos") para
  crear casos difíciles de retrieval.
- [ ] Contenido coherente entre documentos (sin contradicciones con los 3
  existentes ni con las reglas de la tool de vacaciones).
- [ ] Re-ingestar: `python -m src.rag.ingest` (pgvector + Chroma fallback).

**Auditoría de fase (auditor):**
- Consistencia factual entre documentos (números, políticas).
- Sin PII realista ni datos sensibles inventados que parezcan reales.
- Headers markdown correctos (el chunking por headers depende de esto).
- Ningún documento contiene patrones que disparen el sanitizador de ingest.

**Gate:** `scripts/check_vector_store.py` reporta el nuevo total de embeddings
(esperado: ~100+); `make test` verde; spot-check de 3 queries con el retriever.

### Fase 2 — Eval de retrieval (baseline ANTES de optimizar)

**Subagentes:** 1 implementador + auditor.
**Archivos nuevos:** `evals/datasets/retrieval_cases.json`,
`evals/run_retrieval_evals.py`.

- [ ] Dataset: 25–30 casos `{query, expected_sources: [doc o doc§sección], k}`.
  Incluir: queries fáciles, queries con vocabulario ambiguo (los pares
  difíciles de la Fase 1), queries con typos, y queries en inglés (corpus en
  español — mide el embedding multilingüe).
- [ ] Runner: calcula **recall@k** (k=1,3,5) y **MRR**, imprime tabla por caso
  y agregados, `--save` a `evals/results/retrieval_*.json` con commit hash
  (mismo patrón que `run_evals.py`).
- [ ] Target en `Makefile`: `make retrieval-evals`.
- [ ] **Correr contra el retriever actual y commitear el baseline.** Este
  número es el que las fases 3–4 deben batir.

**Auditoría de fase:**
- Los casos no están sesgados a favor de BM25 ni de dense (mezcla de
  keyword-heavy y semánticos).
- `expected_sources` verificados manualmente contra los documentos reales.
- El runner no llama a ningún LLM (retrieval puro, determinista, barato).

**Gate:** `make retrieval-evals` corre y guarda baseline; `make verify` verde.

### Fase 3 — Hybrid search (BM25 + dense + RRF)

**Subagentes:** 1 implementador + auditor.
**Archivos:** `src/rag/retriever.py`, `src/rag/lexical.py` (nuevo),
`src/db/supabase_vector.py`, `requirements.txt` (`rank_bm25`).

- [ ] `src/rag/lexical.py`: índice BM25 en memoria sobre los chunks
  (construido desde el mismo origen que la ingesta; singleton con lazy load,
  mismo patrón que `_get_chroma_vectorstore`). Normalización básica en
  español (lowercase, sin tildes).
- [ ] Fusión **RRF** (`score = Σ 1/(60 + rank)`): función pura
  `rrf_fuse(rankings: list[list[id]]) -> list[id]` con unit tests propios.
- [ ] `search()`: recupera `k_candidates=10` por cada vía (dense + BM25),
  fusiona con RRF, aplica threshold, devuelve top-k. Backends:
  - pgvector: opcional en esta fase usar `tsvector` nativo; si complica,
    BM25 en memoria aplica igual para los tres backends (decisión del
    implementador, documentada). **Preferencia: BM25 en memoria único para
    los 3 backends** (menos código, mismo comportamiento).
- [ ] Flag de configuración `HYBRID_SEARCH_ENABLED` (default `true`) en
  `src/config.py` para poder comparar A/B y hacer rollback barato.
- [ ] `_SearchResult` conserva `retrieval_scores` y `discarded` (no romper
  trazabilidad ni la API del retriever: `rag_agent` y `chain.py` no se tocan).

**Auditoría de fase:**
- API pública de `search()` intacta (firma y tipo de retorno).
- El sanitizador de chunks de ingest sigue aplicándose (sin bypass por la
  vía lexical).
- Sin dependencia nueva salvo `rank_bm25` (versión ≥7 días).
- RRF testeado con casos borde (listas vacías, ids repetidos, un solo ranking).

**Gate:** `make retrieval-evals` → recall@3 y MRR **≥ baseline** (esperado: mejora
en queries keyword-heavy); `make verify` + `make evals` 100%.

### Fase 4 — Reranking con cross-encoder

**Subagentes:** 1 implementador + auditor.
**Archivos:** `src/rag/reranker.py` (nuevo), `src/rag/retriever.py`,
`src/config.py`.

- [ ] `src/rag/reranker.py`: cross-encoder local
  (`cross-encoder/ms-marco-MiniLM-L-6-v2`, ya dentro del ecosistema
  sentence-transformers instalado — verificar que funcione razonablemente en
  español; si no, evaluar `mmarco-mMiniLMv2-L12-H384-v1` multilingüe y
  documentar la elección con números).
- [ ] Pipeline final: hybrid (10 candidatos) → rerank → top 3 al LLM.
- [ ] Flag `RERANKER_ENABLED` (default `true`) + lazy load del modelo
  (singleton; no cargar en import time — cuidado con el arranque de la API
  y los tests).
- [ ] Threshold: el score del cross-encoder reemplaza al de similitud para el
  descarte; recalibrar `RELEVANCE_THRESHOLD` con el dataset de la Fase 2 y
  documentar el valor elegido.
- [ ] Medir y registrar latencia añadida del rerank (objetivo: < 300 ms local
  para 10 candidatos).

**Auditoría de fase:**
- Modelo se carga lazy y una sola vez; tests no descargan el modelo si no
  hace falta (mock o skip marcado).
- Con `RERANKER_ENABLED=false` el comportamiento es idéntico a Fase 3.
- Latencia medida y reportada.

**Gate:** `make retrieval-evals` → MRR **> Fase 3** (el rerank debe justificar
su latencia; si no mejora, se deja el flag en `false` y se documenta —
resultado negativo también es resultado); `make verify` + `make evals` 100%.

### Fase 5 — Citas con sección + cierre

**Subagentes:** 1 implementador + auditor final de TODO el diff acumulado.
**Archivos:** `src/rag/ingest.py`, `src/rag/retriever.py`, `src/rag/chain.py`,
docs.

- [ ] Propagar headers del `MarkdownHeaderTextSplitter` a la metadata del
  chunk y al campo `fuentes`: formato `"politica_rrhh.md § Vacaciones"`.
- [ ] Verificar que el frontend muestra las fuentes nuevas sin romperse
  (solo formato de string; no debería requerir cambios).
- [ ] Re-ingestar y re-correr todo.
- [ ] Documentación: `README.md` (pipeline de retrieval con diagrama),
  `AGENTS.md` (nuevos módulos y flags), `PROGRESS.md` (entrada con tabla
  baseline vs final), `.devin/skills/aegis-desk/SKILL.md`.

**Auditoría final (auditor sobre el diff completo de la feature):**
- Sin código muerto ni flags huérfanos.
- Sin dependencias no usadas en `requirements.txt`.
- Comparar complejidad vs valor: cada módulo nuevo justificado por métrica.
- Checklist de seguridad de la Parte B completo.

**Gate final:** tabla comparativa completa (ver B.4) + `make full` verde.

---

## Parte B — Plan de Auditoría y Testing

### B.1 — Tests unitarios (por fase, TDD donde aplique)

**Archivo nuevo:** `tests/test_rag_avanzado.py` (deterministas, sin red;
Chroma/BM25 local, embeddings locales)

- [ ] `rrf_fuse`: fusión correcta, listas vacías, un solo ranking, empates.
- [ ] BM25: query keyword exacta encuentra el chunk correcto; normalización
  de tildes ("política" == "politica").
- [ ] `search()` híbrido: devuelve `_SearchResult` con `retrieval_scores` y
  `discarded`; respeta `k`; con `HYBRID_SEARCH_ENABLED=false` = dense puro.
- [ ] Reranker: mockeado en tests (no descargar modelo en CI); con flag off,
  pipeline idéntico a hybrid.
- [ ] Ingest: metadata de sección presente en chunks nuevos.
- [ ] Anti-regresión: `rag_agent` y `chain.py` consumen el resultado sin
  cambios (test de integración con retriever real local).

### B.2 — Evals

- [ ] `make retrieval-evals` en cada gate (la métrica central de la feature).
- [ ] `make evals` (37 casos) en cada gate — anti-regresión de respuestas.
- [ ] +3 casos de eval end-to-end con los documentos nuevos (ej. pregunta de
  viáticos, licencia médica, query en inglés).

### B.3 — Red teaming

**Archivo:** `redteam/attacks/payloads.json` (+3 ataques)

- [ ] **Injection vía corpus ampliado**: los docs nuevos pasan por el
  sanitizador de ingest; payload que intenta recuperar un chunk con
  instrucciones → descartado.
- [ ] **Bypass por vía lexical**: query keyword diseñada para traer un chunk
  que el filtro semántico descartaría → el sanitizado es en ingest, no en
  retrieval, así que no debe haber diferencia (verificarlo).
- [ ] **PII en fuentes ampliadas**: `filter_pii` sigue aplicando al contexto
  RAG con el corpus nuevo.

### B.4 — Medición final (el entregable clave)

Tabla obligatoria en `PROGRESS.md`:

| Config | recall@1 | recall@3 | recall@5 | MRR | Latencia p50 |
|---|---|---|---|---|---|
| Baseline (dense, Fase 2) | — | — | — | — | — |
| + Hybrid RRF (Fase 3) | — | — | — | — | — |
| + Reranker (Fase 4) | — | — | — | — | — |

Criterio de cierre: la config final debe superar el baseline en recall@3 y
MRR. Si alguna capa no aporta, se deja detrás de flag apagado y se documenta.

### B.5 — Gates de verificación por fase (resumen)

| Fase | Gate |
|---|---|
| 1 Corpus | check_vector_store (~100+ chunks), make test, spot-check |
| 2 Baseline | make retrieval-evals guarda baseline, make verify |
| 3 Hybrid | retrieval-evals ≥ baseline, make verify + evals 100% |
| 4 Rerank | MRR > Fase 3 (o flag off documentado), make verify + evals |
| 5 Cierre | make full (tests + evals + redteam) + tabla B.4 completa |

Commit por fase; nunca avanzar con un gate rojo o un hallazgo bloqueante del
auditor sin resolver.

---

## Decisiones tomadas

1. **Corpus primero, optimización después** — sin corpus con casos difíciles,
   las mejoras no son medibles.
2. **BM25 en memoria único para los 3 backends** (no `tsvector` por backend):
   menos código, comportamiento uniforme. `tsvector` nativo → backlog.
3. **Flags de configuración** para hybrid y reranker: comparación A/B y
   rollback sin revertir código.
4. **Se acepta el resultado negativo**: si el reranker no mejora MRR, queda
   apagado y documentado — no se fuerza código que no aporta.

## Backlog (fuera de alcance)

- `tsvector`/full-text search nativo en pgvector.
- Query expansion / HyDE.
- Feriados y actualización dinámica del corpus (upload de docs por admin).
- Cache de embeddings de queries frecuentes.
- Evals de retrieval en CI con umbral mínimo (agregar a `verify_all.py --full`).

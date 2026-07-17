# 2. RAG (Retrieval-Augmented Generation)

## Concepto

RAG le da a un LLM acceso a conocimiento externo (documentos privados, actualizados, específicos
de dominio) **sin reentrenarlo**. El flujo estándar:

1. **Ingesta (offline)**: cargar documentos → dividirlos en *chunks* → generar *embeddings* de
   cada chunk → guardarlos en una base de datos vectorial.
2. **Retrieval (en cada query)**: convertir la pregunta del usuario en un embedding → buscar los
   chunks más similares (similitud coseno / distancia euclidiana) en la base vectorial.
3. **Generation**: construir un prompt con los chunks recuperados como contexto + la pregunta →
   pedirle al LLM que responda **basándose únicamente en ese contexto** (grounding).

Por qué RAG en vez de fine-tuning para "el LLM sepa cosas de mi empresa":
- Los documentos cambian constantemente (políticas, FAQs) — reindexar es barato, reentrenar no.
- Permite **citar la fuente** (trazabilidad, auditabilidad) — un modelo fine-tuneado "sabe" algo
  pero no puede decir de dónde lo sacó.
- Reduce alucinaciones porque el modelo tiene el texto exacto delante en vez de tener que
  "recordarlo" de sus pesos.
- Es mucho más barato y rápido de iterar.

## Cómo está implementado en Aegis Desk

### Ingesta — <ref_file file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/rag/ingest.py" />

Pipeline de 3 pasos (`ingest()`):

1. **`load_documents()`**: lee `.md` de `src/rag/documents/` y aplica
   `sanitize_input()` (de `src/security/prompt_injection.py`) a cada documento **antes** de
   indexarlo. Esto es defensa contra **RAG poisoning / indirect prompt injection**: si alguien
   pudiera escribir en los documentos fuente (ej. un wiki interno editable), podría inyectar
   instrucciones tipo `[SYSTEM] ignora tus reglas` que luego se recuperan como "contexto
   confiable" y el LLM las trata como instrucciones legítimas. Sanitizar en ingesta es una capa;
   la otra es que el prompt del LLM en `chain.py` es explícito en que el contexto son *datos*, no
   instrucciones.

2. **`split_documents()` — chunking en 2 pasos**:
   - Paso 1: `MarkdownHeaderTextSplitter` parte por encabezados (`#`, `##`, `###`) — esto
     respeta la **estructura semántica** del documento (cada sección de política queda junta)
     en vez de cortar a tamaño fijo ciegamente.
   - Paso 2: `RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)` — si una sección
     sigue siendo muy larga, la parte más, con **overlap** para no cortar una idea a la mitad
     entre dos chunks consecutivos.
   - Esto es un ejemplo de **chunking jerárquico/estructural** vs chunking naive por caracteres.
     El trade-off de chunk_size: chunks muy pequeños → más precisión en qué se recupera pero
     menos contexto por chunk; chunks muy grandes → más contexto pero más "ruido" y menor
     precisión del embedding (mezcla temas).

3. **`create_vectorstore()`**: genera embeddings con `LocalEmbeddings` (wrapper de
   sentence-transformers, ver archivo 3). En producción, cuando `DATABASE_URL` está configurado,
   los guarda en **Supabase pgvector** (`src/db/supabase_vector.py`, tabla `document_embeddings`,
   `embedding vector(384)`, índice HNSW `vector_cosine_ops`). Si no hay `DATABASE_URL`, cae a
   **Chroma** persistente en disco (`data/chroma/`, `collection_name="aegis_docs"`). Chroma se
   mantiene también como fallback/copia local; el pipeline siempre crea/actualiza Chroma y, si
   está configurado Supabase, hace `upsert` adicional a Postgres.

### Retrieval — <ref_file file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/rag/retriever.py" />

- `search(query, k=3)` elige el backend en runtime (<ref_file file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/rag/retriever.py" />):
  - Si `DATABASE_URL` está set, usa **Supabase pgvector** (`src/db/supabase_vector.py`):
    cosine distance (`embedding <=> %s::vector`) y convierte la distancia a `score = 1 - distance`
    (**mayor** score = más similar).
  - Si `PINECONE_API_KEY` está configurado, usa Pinecone.
  - Si no, cae a **Chroma** local. `get_vectorstore()` sigue siendo un singleton que carga Chroma
    del disco una sola vez; `similarity_search_with_score` devuelve `score` como **distancia**
    (menor = más similar).
- Es fácil confundir el score según backend: en Supabase `score` es similitud (mayor = mejor),
  en Chroma es distancia (menor = mejor). La capa `retriever.py` normaliza ambos a un float
  comparable antes de pasarlo al resto del grafo.

**Nota de producción (Supabase pgvector):** Cuando `DATABASE_URL` está configurado, el vector
store por defecto es Supabase Postgres/pgvector. La extensión `vector` vive en el schema
`extensions`, todas las tablas del schema `public` tienen **RLS** habilitado, y la conexión
recomendada usa el **Connection Pooler / Supavisor** de Supabase para evitar problemas de IPv4/IPv6.
Las credenciales son `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_KEY` y `SUPABASE_SERVICE_KEY`
(service key solo en backend). Ver <ref_file file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/db/postgres_utils.py" /> para normalización de la URL (`search_path=public,extensions`).

### Generation — <ref_file file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/rag/chain.py" />

- `rag_query()`: recupera chunks → los formatea con `[i] Fuente: archivo.md` → los inyecta en un
  `SYSTEM_PROMPT` con reglas explícitas de **grounding**:
  1. Responder solo con lo que está en los documentos.
  2. Citar la fuente.
  3. Decir "no tengo información" si no está — esto es clave para reducir alucinaciones (el
     prompt le da una "salida honesta" en vez de forzar una respuesta).
  4. `temperature=0` — para respuestas más deterministas/factuales (menos "creatividad" cuando
     lo que quieres es fidelidad a una fuente).
- Después de generar, se aplica `filter_pii()` a la respuesta antes de devolverla (ver archivo 5)
  — un LLM podría repetir un email o dato sensible que estaba en el chunk recuperado.

### Métricas / evaluación RAG

Ver archivo 7 (`evals/rag_evals.py`) para faithfulness, answer relevance, context precision —
son las tres métricas clásicas de RAGAS, implementadas aquí de forma simplificada con LLM-as-judge
en vez de NLI models.

## Limitaciones honestas del RAG actual (para hablar con criterio en entrevista)

- `k=3` fijo, sin *re-ranking* posterior (no hay un segundo paso que reordene los chunks
  recuperados por relevancia real a la pregunta — solo similitud vectorial cruda).
- No hay **hybrid search** (combinar búsqueda vectorial + BM25/keyword) — para preguntas con
  términos exactos (ej. un ID de ticket) la búsqueda semántica pura puede fallar.
- No hay *query rewriting/expansion* (reformular la pregunta del usuario antes de buscar).
- El chunking es por Markdown — funciona bien para documentos estructurados, no generalizaría
  igual de bien a PDFs escaneados o texto sin estructura.

## Preguntas de entrevista

**P: Explícame el pipeline de RAG de tu proyecto de punta a punta.**
> Ingesta con sanitización → chunking en dos pasos respetando Markdown → embeddings locales con
> sentence-transformers → Supabase pgvector en producción (o Chroma local como fallback) →
> retrieval con similarity search top-k (pgvector con índice HNSW/cosine, o Chroma local) →
> prompt con reglas de grounding y citación → post-filtro de PII.

**P: ¿Cómo decidiste el tamaño de chunk?**
> Primero parto por headers de Markdown para que cada chunk sea una unidad semántica completa
> (una sección de política), y solo si una sección excede 500 caracteres la subdivido más con
> overlap de 50 para no perder contexto en el borde. Es un enfoque híbrido: estructura primero,
> tamaño fijo como red de seguridad.

**P: ¿Cómo evitas que el modelo alucine con RAG?**
> Tres cosas: (1) el prompt de sistema obliga a responder solo con el contexto y a decir
> explícitamente "no tengo información" si no está — le doy una salida honesta; (2)
> `temperature=0` para reducir variabilidad/creatividad; (3) evaluamos `faithfulness` con
> LLM-as-judge en la suite de evals, comparando cada afirmación de la respuesta contra las
> fuentes recuperadas.

**P: ¿Qué es RAG poisoning y cómo te proteges?**
> Es cuando el contenido indexado (no el input del usuario) contiene una inyección de prompt —
> por ejemplo un documento con `[SYSTEM] ignora tus reglas`. Si se recupera como contexto, el
> LLM podría tratarlo como instrucción legítima. Me protejo sanitizando el contenido en la etapa
> de ingesta (antes de indexar) y siendo explícito en el prompt de que el contenido recuperado es
> *información de referencia*, no instrucciones del sistema.

**P: ¿Por qué Supabase pgvector y no Chroma/Pinecone/Weaviate?**
> En producción uso **Supabase pgvector** (PostgreSQL gestionado) porque unifica datos
> estructurados, cola HITL, checkpointer y vectores en una sola base, con RLS y backups. Chroma
> local sigue disponible como fallback cuando no hay `DATABASE_URL`, y Pinecone sigue soportado si
> se configura `PINECONE_API_KEY`. La capa de abstracción en `retriever.py` elige el backend en
> runtime, así que el resto del código no depende directamente de uno u otro.

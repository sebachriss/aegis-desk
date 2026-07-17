# 3. Embeddings y bases de datos vectoriales

## Concepto

Un **embedding** es una representación numérica (vector de N dimensiones) de un texto, generada
por un modelo entrenado para que textos con significado similar queden **cerca** en ese espacio
vectorial (medido por distancia coseno, euclidiana, o producto punto). Esto permite "búsqueda
semántica": encontrar documentos relevantes por significado, no por coincidencia exacta de
palabras.

Tipos de modelos de embeddings:
- **Modelos locales open-source** (sentence-transformers, BGE, E5): corren en tu propia máquina/
  servidor, no hay costo por llamada, pero consumen CPU/GPU local y suelen tener menor calidad
  que los modelos comerciales grandes.
- **Modelos vía API** (OpenAI `text-embedding-3`, Cohere, Voyage): mejor calidad/generalización
  en muchos benchmarks, pero cuestan dinero por token y tienen latencia de red.

Dimensiones más grandes generalmente capturan más matices semánticos pero cuestan más
almacenamiento y cómputo en la búsqueda (más lento el cálculo de similitud a escala).

Una **vector database** (Chroma, Pinecone, Weaviate, pgvector, Qdrant, FAISS) indexa estos
vectores con estructuras como HNSW (Hierarchical Navigable Small World) o IVF para hacer
*approximate nearest neighbor search* (ANN) — búsqueda de los k vecinos más cercanos sin tener
que comparar contra todos los vectores (que sería O(n) y no escalaría).

## Cómo está implementado en Aegis Desk

- **Modelo**: `all-MiniLM-L6-v2` de `sentence-transformers`
  (<ref_snippet file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/rag/ingest.py" lines="25-29" />).
  - 90MB, corre local (no requiere API key ni costo por llamada).
  - Genera vectores de **384 dimensiones**.
  - Es un modelo *distilled* (destilado de un modelo más grande) optimizado para
    velocidad/tamaño manteniendo buena calidad para tareas generales de similitud semántica —
    trade-off consciente: no es el mejor embedding disponible (modelos como
    `text-embedding-3-large` o BGE-large tienen mejor recall en benchmarks como MTEB), pero es
    gratis, rápido, y suficiente para un corpus pequeño de documentos internos.

- **`LocalEmbeddings`** (misma sección del archivo): es un **wrapper/adapter**. LangChain espera
  objetos con `embed_documents(list[str]) -> list[list[float]]` y
  `embed_query(str) -> list[float]`, pero `sentence-transformers` no expone esa interfaz
  nativamente (usa `.encode()`). Este patrón de adapter es común cuando integras una librería de
  ML con un framework que espera una interfaz específica.
  - `embed_documents`: se usa en **ingesta** (batch, muchos textos a la vez → más eficiente).
  - `embed_query`: se usa en **retrieval** (un solo texto, la pregunta del usuario).
  - Nota importante: aunque el método es distinto, ambos usan el mismo modelo — es clave que
    documento y query se embedan con el **mismo modelo** o los vectores no son comparables.

- **Vector store**: en producción **Supabase pgvector** (`src/db/supabase_vector.py`), tabla
  `document_embeddings` con `embedding vector(384)` e índice HNSW `vector_cosine_ops`. Usa
  cosine distance (`embedding <=> query::vector`) y devuelve `score = 1 - distance` (mayor = más
  similar). Si no hay `DATABASE_URL`, el fallback es **Chroma** persistente en `data/chroma/`,
  colección `aegis_docs` (<ref_file file="/Users/sebastianceron/Desktop/Seba/Study/aegis-desk/src/rag/retriever.py" />).
  Chroma usa HNSW internamente para la búsqueda ANN; `similarity_search_with_score` devuelve
  `score` como **distancia** — a menor score, más similar. Es un detalle fácil de confundir en
  entrevista: Supabase devuelve similitud (mayor = mejor), Chroma devuelve distancia (menor = mejor).

**Nota de producción (Supabase):** `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_KEY` y
`SUPABASE_SERVICE_KEY` son las variables de entorno que activan el backend de Supabase. La
extensión `vector` se instala en el schema `extensions`, todas las tablas `public` tienen
**RLS** habilitado, y la conexión recomendada usa el **Connection Pooler / Supavisor** de
Supabase para evitar problemas de IPv6 (con percent-encoding en el password para `$`, `@` y `%`).

## Preguntas de entrevista

**P: ¿Por qué elegiste ese modelo de embeddings y qué trade-offs implica?**
> `all-MiniLM-L6-v2` porque es local, gratis, rápido (384 dims, modelo chico) y suficiente para un
> corpus pequeño de documentos internos de una empresa ficticia. El trade-off es calidad: modelos
> más grandes (OpenAI `text-embedding-3-large`, BGE-large, dimensiones 1536-3072) capturan más
> matices semánticos y tienen mejor recall en benchmarks tipo MTEB, pero cuestan dinero por
> llamada y añaden latencia de red. Para un proyecto en producción con más volumen o dominios más
> ambiguos, evaluaría ese upgrade con un eval de context precision antes/después.

**P: ¿Cómo funciona la búsqueda semántica bajo el capó?**
> Se embeben todos los chunks al indexar y se guardan en el vector store. Cuando llega una query,
> se embebe con el mismo modelo, y el vector store hace *approximate nearest neighbor search*
> (en Supabase pgvector con índice HNSW/cosine; fallback Chroma local con HNSW) para encontrar
> los k vectores más cercanos. En Supabase se usa cosine distance (`<=>`) y se expone como
> `score = 1 - distance`; en Chroma el score es la distancia directa. Es "semántico" porque el
> modelo de embeddings fue entrenado para que frases con significado similar (aunque usen
> palabras distintas) queden cerca en el espacio vectorial.

**P: ¿Qué pasaría si cambias el modelo de embeddings después de haber indexado documentos?**
> Tendría que reindexar todo — los vectores de un modelo no son comparables con los de otro (ni
> siquiera si tienen la misma dimensión, los espacios vectoriales son distintos). Es un detalle
> operacional importante: cambiar de modelo de embeddings implica migración completa del vector
> store, no es un cambio "en caliente".

**P: ¿Qué es HNSW y por qué importa a escala?**
> Es una estructura de grafo jerárquico para *approximate nearest neighbor search*. Sin ella,
> encontrar los k vecinos más cercanos requeriría comparar la query contra cada vector indexado
> (O(n)), lo cual no escala a millones de documentos. HNSW logra búsquedas sub-lineales a costa
> de exactitud (por eso "approximate", no exacto) — un trade-off aceptable para RAG donde
> recuperar el top-k "casi perfecto" es suficiente.

**P: ¿Embeddings locales vs API — cuándo usarías cada uno?**
> Locales: cuando el volumen es alto y quieres evitar costo por llamada, cuando hay
> restricciones de datos (no quieres mandar contenido sensible a una API externa), o cuando la
> latencia de red es un problema. API: cuando necesitas la mejor calidad posible y el volumen es
> manejable en costo, o no quieres mantener infraestructura de ML local (descarga de modelos,
> GPU/CPU, versionado).

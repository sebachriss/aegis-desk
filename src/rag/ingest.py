"""Pipeline de ingesta: lee documentos, los parte en chunks, genera embeddings y los guarda en Chroma.

Flujo:
  1. Leer archivos .md de src/rag/documents/
  2. Partir cada documento en chunks (RecursiveCharacterTextSplitter)
  3. Generar embeddings con sentence-transformers (local, gratis)
  4. Guardar todo en Chroma (base de datos vectorial local persistente)
"""

from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from src.db.pinecone_store import is_pinecone_configured, upsert_documents as upsert_pinecone
from src.db.supabase_vector import is_supabase_vector_configured, upsert_documents as upsert_supabase
from src.rag.embeddings import EMBEDDING_MODEL, LocalEmbeddings
from src.security.prompt_injection import detect_prompt_injection, sanitize_input

# Ruta donde se guardan los documentos fuente
DOCUMENTS_DIR = Path(__file__).parent / "documents"

# Ruta donde Chroma guarda la base de datos (persistente en disco)
CHROMA_DIR = Path(__file__).parent.parent.parent / "data" / "chroma"


def load_documents() -> list[Document]:
    """Lee todos los archivos .md de la carpeta documents y los convierte en Document.

    Document es el formato de LangChain: tiene .page_content (el texto)
    y .metadata (diccionario con info extra, ej: el nombre del archivo).
    """
    documents = []

    for file_path in sorted(DOCUMENTS_DIR.glob("*.md")):
        content = file_path.read_text(encoding="utf-8")
        # Fase 5/6: sanitizar inyecciones de prompt antes de indexar (RAG poisoning)
        content = sanitize_input(content)
        doc = Document(
            page_content=content,
            metadata={"source": file_path.name},
        )
        documents.append(doc)
        print(f"  Cargado: {file_path.name} ({len(content)} caracteres)")

    return documents


def _is_safe_chunk(chunk: Document) -> bool:
    """Rechaza chunks que contengan intentos de inyeccion de instrucciones."""
    text = chunk.page_content
    injection_check = detect_prompt_injection(text)
    if injection_check["is_injection"]:
        print(f"    [RECHAZADO] chunk de {chunk.metadata.get('source', '?')} contiene inyeccion: {injection_check['matched_pattern']}")
        return False
    return True


def split_documents(documents: list[Document]) -> list[Document]:
    """Parte documentos en chunks respetando la estructura Markdown.

    Paso 1: MarkdownHeaderTextSplitter
      Parte por encabezados (##, ###). Cada seccion queda como un chunk.
      Ej: "## Vacaciones" -> un chunk con solo el contenido de vacaciones.
      Metadata incluye el titulo de la seccion.

    Paso 2: RecursiveCharacterTextSplitter
      Si alguna seccion es muy larga (>500 caracteres), la parte mas.
      chunk_overlap=50 para no cortar ideas a la mitad.

    Paso 3: Filtro anti-inyeccion
      Descarta chunks que contengan instrucciones de sistema, role overrides,
      o patrones de prompt injection detectados por el security detector.
    """
    # Paso 1: partir por encabezados Markdown
    # Los encabezados que usamos: # (titulo), ## (seccion), ### (subseccion)
    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[
            ("#", "header_1"),
            ("##", "header_2"),
            ("###", "header_3"),
        ],
    )

    section_chunks = []
    for doc in documents:
        source = doc.metadata["source"]
        # MarkdownHeaderTextSplitter recibe texto, no Document
        sections = header_splitter.split_text(doc.page_content)

        for section in sections:
            # Preservar el source original + añadir info del encabezado
            section.metadata["source"] = source
            section_chunks.append(section)

    print(f"  Paso 1: {len(documents)} documentos -> {len(section_chunks)} secciones")

    # Paso 2: si alguna seccion es muy larga, partirla mas
    size_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
        separators=["\n\n", "\n", " ", ""],
    )

    chunks = size_splitter.split_documents(section_chunks)

    # Paso 3: filtrar chunks con intentos de prompt injection / instrucciones ocultas
    safe_chunks = [chunk for chunk in chunks if _is_safe_chunk(chunk)]
    rejected = len(chunks) - len(safe_chunks)

    # Mostrar info de cada chunk para debug
    for chunk in safe_chunks:
        header = chunk.metadata.get("header_2", chunk.metadata.get("header_1", ""))
        print(f"    [{chunk.metadata['source']}] {header} ({len(chunk.page_content)} chars)")

    if rejected:
        print(f"  [SEGURIDAD] {rejected} chunk(s) rechazados por contenido sospechoso")

    print(f"  Paso 2/3: {len(section_chunks)} secciones -> {len(chunks)} chunks -> {len(safe_chunks)} seguros")
    return safe_chunks


def create_vectorstore(chunks: list[Document]) -> Chroma:
    """Crea (o sobreescribe) la base de datos Chroma con los chunks.

    Si Pinecone está configurado, también sube los chunks al índice remoto.

    Chroma guarda:
      - El texto de cada chunk
      - Su vector (embedding)
      - Sus metadatos (ej: source = nombre del archivo)

    La base se persiste en disco (CHROMA_DIR), asi que sobrevive reinicios.
    """
    embeddings = LocalEmbeddings()

    # Asegurar que el directorio existe
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)

    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=str(CHROMA_DIR),
        collection_name="aegis_docs",
    )

    if is_pinecone_configured():
        print("  Subiendo chunks a Pinecone...")
        pinecone_docs = [
            {
                "id": f"{chunk.metadata.get('source', 'doc')}_{i}",
                "content": chunk.page_content,
                "source": chunk.metadata.get("source", "desconocido"),
            }
            for i, chunk in enumerate(chunks)
        ]
        upsert_pinecone(pinecone_docs)
        print("  Pinecone actualizado.")

    if is_supabase_vector_configured():
        print("  Subiendo chunks a Supabase pgvector...")
        embeddings_model = LocalEmbeddings()
        embs = embeddings_model.embed_documents([c.page_content for c in chunks])
        upsert_supabase(chunks, embs)
        print("  Supabase pgvector actualizado.")

    print(f"  Base de datos creada en: {CHROMA_DIR}")
    print(f"  Total chunks indexados: {len(chunks)}")
    return vectorstore


def ingest() -> Chroma:
    """Ejecuta el pipeline completo: cargar -> partir -> indexar.

    Returns:
        Chroma: la base de datos vectorial lista para hacer busquedas.
    """
    print("\n=== Ingesta de documentos ===\n")

    print("1. Cargando documentos...")
    documents = load_documents()

    print("\n2. Partiendo en chunks...")
    chunks = split_documents(documents)

    print("\n3. Generando embeddings y guardando en Chroma...")
    vectorstore = create_vectorstore(chunks)

    print("\n=== Ingesta completada ===\n")
    return vectorstore


if __name__ == "__main__":
    ingest()

"""Streamlit UI para Aegis Desk.

Tres vistas:
  1. Chat — conversar con el agente
  2. Aprobaciones HITL — aprobar/rechazar acciones pendientes
  3. Dashboard — métricas de tracing

Ejecutar:
  streamlit run ui/app.py

Requiere que la API esté corriendo:
  uvicorn src.api.main:app --reload --port 8000
"""

import requests

import streamlit as st

API_URL = "http://localhost:8000"

st.set_page_config(
    page_title="Aegis Desk",
    page_icon="🛡️",
    layout="wide",
)

# --- Sidebar ---

st.sidebar.title("🛡️ Aegis Desk")
st.sidebar.caption("Soporte interno inteligente")

vista = st.sidebar.radio(
    "Navegación",
    ["💬 Chat", "✅ Aprobaciones HITL", "📊 Dashboard"],
)

# --- Session state ---

if "messages" not in st.session_state:
    st.session_state.messages = []

if "pending_hitl" not in st.session_state:
    st.session_state.pending_hitl = []

if "user_id" not in st.session_state:
    st.session_state.user_id = "ui_user"

if "role" not in st.session_state:
    st.session_state.role = "empleado"


# --- Vista: Chat ---

if vista == "💬 Chat":
    st.title("💬 Chat con Aegis")

    # Configuración de usuario
    col1, col2 = st.columns([1, 1])
    with col1:
        st.session_state.user_id = st.text_input("User ID", value=st.session_state.user_id)
    with col2:
        st.session_state.role = st.selectbox("Rol", ["empleado", "admin"], index=0)

    st.divider()

    # Historial de mensajes
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("metadata"):
                with st.expander("Detalles"):
                    st.json(msg["metadata"])

    # Input
    if prompt := st.chat_input("Escribe tu consulta..."):
        # Mostrar mensaje del usuario
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Llamar a la API
        with st.chat_message("assistant"):
            with st.spinner("Procesando..."):
                try:
                    resp = requests.post(
                        f"{API_URL}/chat",
                        json={
                            "query": prompt,
                            "user_id": st.session_state.user_id,
                            "role": st.session_state.role,
                        },
                        timeout=120,
                    )
                    data = resp.json()
                except requests.exceptions.ConnectionError:
                    st.error("❌ No se pudo conectar a la API. ¿Está corriendo `uvicorn src.api.main:app --port 8000`?")
                    st.stop()
                except Exception as e:
                    st.error(f"❌ Error: {e}")
                    st.stop()

            st.markdown(data["respuesta"])

            metadata = {
                "thread_id": data["thread_id"],
                "intencion": data["intencion"],
                "confidence": data["confidence"],
                "elapsed_seconds": data["elapsed_seconds"],
                "fuentes": data["fuentes"],
            }

            with st.expander("Detalles"):
                st.json(metadata)

            # Si requiere HITL, agregar a pendientes
            if data.get("requires_hitl"):
                st.warning("⏸️ Esta acción requiere aprobación humana. Ve a la vista 'Aprobaciones HITL'.")
                st.session_state.pending_hitl.append({
                    "thread_id": data["thread_id"],
                    "query": prompt,
                    "intencion": data["intencion"],
                })

            st.session_state.messages.append({
                "role": "assistant",
                "content": data["respuesta"],
                "metadata": metadata,
            })


# --- Vista: Aprobaciones HITL ---

elif vista == "✅ Aprobaciones HITL":
    st.title("✅ Aprobaciones Pendientes")

    if not st.session_state.pending_hitl:
        st.info("No hay acciones pendientes de aprobación.")
    else:
        for i, item in enumerate(st.session_state.pending_hitl):
            with st.container(border=True):
                st.write(f"**Thread:** `{item['thread_id']}`")
                st.write(f"**Consulta:** {item['query']}")
                st.write(f"**Intención:** {item['intencion']}")

                col1, col2 = st.columns(2)

                with col1:
                    if st.button(f"✅ Aprobar", key=f"approve_{i}"):
                        try:
                            resp = requests.post(
                                f"{API_URL}/hitl/{item['thread_id']}/approve",
                                timeout=60,
                            )
                            data = resp.json()
                            st.success(f"Aprobado: {data.get('respuesta', '')[:100]}")
                        except Exception as e:
                            st.error(f"Error: {e}")

                        # Remover de pendientes
                        st.session_state.pending_hitl.pop(i)
                        st.rerun()

                with col2:
                    if st.button(f"❌ Rechazar", key=f"reject_{i}"):
                        try:
                            resp = requests.post(
                                f"{API_URL}/hitl/{item['thread_id']}/reject",
                                timeout=60,
                            )
                            data = resp.json()
                            st.warning(f"Rechazado: {data.get('respuesta', '')[:100]}")
                        except Exception as e:
                            st.error(f"Error: {e}")

                        # Remover de pendientes
                        st.session_state.pending_hitl.pop(i)
                        st.rerun()


# --- Vista: Dashboard ---

elif vista == "📊 Dashboard":
    st.title("📊 Dashboard de Métricas")

    try:
        resp = requests.get(f"{API_URL}/stats", timeout=10)
        stats = resp.json()
    except requests.exceptions.ConnectionError:
        st.error("❌ No se pudo conectar a la API. ¿Está corriendo?")
        st.stop()

    if stats.get("total", 0) == 0:
        st.info("No hay datos de tracing todavía. Envía algunos mensajes en el Chat.")
    else:
        # Métricas principales
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Total ejecuciones", stats["total"])
        with col2:
            st.metric("Confidence promedio", f"{stats['avg_confidence']:.3f}")
        with col3:
            st.metric("Tiempo promedio", f"{stats['avg_elapsed']:.2f}s")
        with col4:
            st.metric("Bloqueadas", stats.get("blocked", 0))

        st.divider()

        # Por intención
        st.subheader("Por intención")
        by_intencion = stats.get("by_intencion", {})

        if by_intencion:
            col_data = []
            for intencion, data in sorted(by_intencion.items()):
                col_data.append({
                    "Intención": intencion,
                    "Casos": data["count"],
                    "Avg Confidence": data["avg_confidence"],
                })

            st.dataframe(col_data, use_container_width=True)

            # Gráfico de barras simple
            st.bar_chart(
                {intencion: data["count"] for intencion, data in sorted(by_intencion.items())},
                use_container_width=True,
            )

        st.divider()

        # Reintentos
        st.subheader("Reintentos")
        st.metric("Total reintentos", stats.get("total_retries", 0))

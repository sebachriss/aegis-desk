"""Streamlit UI para Aegis Desk.

Vistas:
  0. Login — autenticar usuario y obtener JWT token
  1. Chat — conversar con el agente
  2. Aprobaciones HITL — aprobar/rechazar acciones pendientes
  3. Dashboard — métricas de tracing

Ejecutar:
  streamlit run ui/app.py

Requiere que la API esté corriendo:
  uvicorn src.api.main:app --reload --port 8000
"""

import os
import requests

import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000")

st.set_page_config(
    page_title="Aegis Desk",
    page_icon="🛡️",
    layout="wide",
)

# --- Session state ---

if "token" not in st.session_state:
    st.session_state.token = None

if "user" not in st.session_state:
    st.session_state.user = None

if "messages" not in st.session_state:
    st.session_state.messages = []

if "pending_hitl" not in st.session_state:
    st.session_state.pending_hitl = []


def api_headers():
    """Devuelve headers con token JWT si hay sesión activa."""
    headers = {}
    if st.session_state.token:
        headers["Authorization"] = f"Bearer {st.session_state.token}"
    return headers


# --- Login ---

if not st.session_state.token:
    st.title("🛡️ Aegis Desk — Login")
    st.caption("Plataforma de soporte interno inteligente")

    with st.form("login_form"):
        username = st.text_input("Usuario", placeholder="ana.garcia")
        password = st.text_input("Contraseña", type="password")
        submitted = st.form_submit_button("Iniciar sesión")

        if submitted:
            try:
                resp = requests.post(
                    f"{API_URL}/login",
                    json={"username": username, "password": password},
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    st.session_state.token = data["access_token"]
                    st.session_state.user = {
                        "username": username,
                        "role": data["role"],
                        "display_name": data["display_name"],
                    }
                    st.success(f"Bienvenido, {data['display_name']}!")
                    st.rerun()
                else:
                    st.error("❌ Usuario o contraseña incorrectos")
            except requests.exceptions.ConnectionError:
                st.error("❌ No se pudo conectar a la API. ¿Está corriendo `uvicorn src.api.main:app --port 8000`?")
            except Exception as e:
                st.error(f"❌ Error: {e}")

    with st.expander("Usuarios de prueba"):
        st.write("| Usuario | Password | Rol |")
        st.write("|---|---|---|")
        st.write("| ana.garcia | ana123 | empleado |")
        st.write("| carlos.lopez | carlos123 | empleado |")
        st.write("| admin.aegis | admin123 | admin |")

    st.stop()


# --- Sidebar ---

st.sidebar.title("🛡️ Aegis Desk")
st.sidebar.caption(f"Sesión: {st.session_state.user['display_name']}")
st.sidebar.write(f"Rol: **{st.session_state.user['role']}**")

if st.sidebar.button("Cerrar sesión"):
    st.session_state.token = None
    st.session_state.user = None
    st.session_state.messages = []
    st.session_state.pending_hitl = []
    st.rerun()

vista = st.sidebar.radio(
    "Navegación",
    ["💬 Chat", "✅ Aprobaciones HITL", "📊 Dashboard"],
)


# --- Vista: Chat ---

if vista == "💬 Chat":
    st.title("💬 Chat con Aegis")

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
                        json={"query": prompt},
                        headers=api_headers(),
                        timeout=120,
                    )
                    if resp.status_code == 401:
                        st.error("❌ Sesión expirada. Cierra sesión y vuelve a iniciar.")
                        st.stop()
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

    if st.session_state.user["role"] != "admin":
        st.warning("⚠️ Solo los administradores pueden aprobar/rechazar acciones.")
    elif not st.session_state.pending_hitl:
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
                                headers=api_headers(),
                                timeout=60,
                            )
                            if resp.status_code == 403:
                                st.error("❌ No tienes permisos de admin.")
                            else:
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
                                headers=api_headers(),
                                timeout=60,
                            )
                            if resp.status_code == 403:
                                st.error("❌ No tienes permisos de admin.")
                            else:
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
        resp = requests.get(f"{API_URL}/stats", headers=api_headers(), timeout=10)
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

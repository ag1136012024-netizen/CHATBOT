import json
import time
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

# ==========================================
# 1. METADATOS Y CONFIGURACIÓN DE PÁGINA
# ==========================================

APP_VERSION = "v4.0 - Voz + Estado en vivo 🎤"

st.set_page_config(
    page_title="Friday - Tu Tutor Virtual",
    page_icon="🤖",
    layout="centered",
    initial_sidebar_state="expanded"
)

# ==========================================
# 2. CONFIGURACIÓN SEGURA DE LA API KEY
# ==========================================

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
except KeyError:
    st.error(
        "⚠️ Falta configurar la API Key. "
        "Agrega GOOGLE_API_KEY en los Secrets de Streamlit Cloud (.streamlit/secrets.toml)."
    )
    st.stop()

# ==========================================
# 3. PROMPTS DEL SISTEMA (MODOS DE TUTORÍA)
# ==========================================

SYSTEM_PROMPTS = {
    "Tutor General": """
    Eres Friday, una tutora virtual amigable, inteligente y humana.
    - Habla de forma natural, cercana y paciente.
    - Usa ejemplos claros y sencillos.
    - Nunca reveles que eres una IA, un chatbot o un modelo de lenguaje.
    - Si no sabes algo, dilo con honestidad y ofrece una alternativa útil.
    - Responde siempre en el idioma utilizado por el usuario.
    - Explica los temas paso a paso cuando sea necesario.
    - Ayuda al usuario con tareas, programación, tecnología, matemáticas y temas académicos.
    """,
    "Experto en Programación": """
    Eres Friday en modo Code Mentor.
    - Te especializas en desarrollo de software, algoritmos y depuración de código.
    - Formatea siempre los bloques de código adecuadamente especificado el lenguaje.
    - Explica la lógica detrás de cada función o solución propuesta.
    - Ofrece mejores prácticas de programación y optimización.
    - Nunca reveles que eres una IA o modelo de lenguaje.
    """,
    "Explicación Sencilla (ELI5)": """
    Eres Friday en modo Simplificado.
    - Explica conceptos complejos como si el usuario tuviera 10 años.
    - Utiliza analogías del mundo real, metáforas y un lenguaje libre de modismos técnicos innecesarios.
    - Mantén las respuestas breves, didácticas y entretenidas.
    - Nunca reveles que eres una IA o modelo de lenguaje.
    """
}

# ==========================================
# 3.05 NUEVO: BASE DE CONOCIMIENTO (para "nutrir" a Friday)
# ==========================================
# Escribe información en el archivo conocimiento.txt (junto a este archivo)
# y Friday la usará como referencia en sus respuestas.

@st.cache_data
def load_knowledge() -> str:
    archivo = Path(__file__).parent / "conocimiento.txt"
    if archivo.exists():
        return archivo.read_text(encoding="utf-8").strip()
    return ""

KNOWLEDGE = load_knowledge()

# ==========================================
# 3.1 NUEVO: MENSAJES DE ESTADO VARIABLES
# ==========================================
# Lo que Friday "está haciendo" cambia según el modo y el tipo de pregunta.

def get_status_steps(mode: str, prompt: str) -> list[str]:
    """Devuelve la lista de pasos que se mostrarán mientras Friday prepara la respuesta."""
    p = prompt.lower()
    steps = ["🧠 Leyendo y entendiendo tu pregunta..."]

    # Detección simple del tipo de consulta
    palabras_codigo = ["código", "codigo", "python", "error", "bug", "función", "funcion",
                       "java", "javascript", "html", "sql", "```", "programa", "algoritmo"]
    palabras_mate = ["calcula", "ecuación", "ecuacion", "derivada", "integral", "suma",
                     "resta", "multiplica", "matemática", "matematica", "porcentaje"]

    if mode == "Experto en Programación" or any(w in p for w in palabras_codigo):
        steps += [
            "💻 Analizando el problema de programación...",
            "🔍 Revisando la lógica y posibles errores...",
            "🧩 Armando la solución con ejemplos de código...",
        ]
    elif any(w in p for w in palabras_mate):
        steps += [
            "🧮 Identificando el tipo de problema matemático...",
            "📐 Resolviendo paso a paso...",
        ]
    elif mode == "Explicación Sencilla (ELI5)":
        steps += [
            "🎈 Buscando una analogía fácil de entender...",
            "✂️ Simplificando las palabras complicadas...",
        ]
    else:
        steps += [
            "📚 Buscando la mejor forma de explicártelo...",
            "💡 Pensando en ejemplos claros...",
        ]

    steps.append("✍️ Escribiendo la respuesta...")
    return steps

# ==========================================
# 3.2 NUEVO: COMPONENTE DE DICTADO DE VOZ
# ==========================================
# Usa la Web Speech API del navegador (gratis, sin librerías extra).
# Lo que dices aparece EN VIVO dentro de la caja de chat.
# Funciona en Chrome y Edge (no en Firefox).

VOICE_HTML = """
<script>
(function () {
  const LANG = "__LANG__";
  const AUTO_SEND = __AUTO__;
  const P = window.parent;      // página de Streamlit
  const D = P.document;

  const SR = P.SpeechRecognition || P.webkitSpeechRecognition ||
             window.SpeechRecognition || window.webkitSpeechRecognition;

  // Estilos del botón (se inyectan una sola vez en la página principal)
  if (!D.getElementById("friday-mic-style")) {
    const st = D.createElement("style");
    st.id = "friday-mic-style";
    st.textContent = `
      #friday-mic {
        width: 34px; height: 34px; border-radius: 50%; border: none;
        background: transparent; cursor: pointer; font-size: 18px;
        display: inline-flex; align-items: center; justify-content: center;
        margin-right: 4px; flex-shrink: 0;
      }
      #friday-mic:hover { background: rgba(128,128,128,.25); }
      #friday-mic.on { background: #16a34a; animation: fridayPulse 1.2s infinite; }
      #friday-mic:disabled { opacity: .35; cursor: not-allowed; }
      @keyframes fridayPulse {
        0%   { box-shadow: 0 0 0 0 rgba(22,163,74,.6); }
        70%  { box-shadow: 0 0 0 10px rgba(22,163,74,0); }
        100% { box-shadow: 0 0 0 0 rgba(22,163,74,0); }
      }`;
    D.head.appendChild(st);
  }

  // Quitar botón anterior (por si la página se recargó) y crear uno nuevo
  const old = D.getElementById("friday-mic");
  if (old) old.remove();

  const btn = D.createElement("button");
  btn.id = "friday-mic";
  btn.type = "button";
  btn.title = "Dictar por voz";
  btn.textContent = "🎤";

  function getInput() {
    return D.querySelector('textarea[data-testid="stChatInputTextArea"]');
  }
  function setInput(text) {
    const ta = getInput();
    if (!ta) return;
    const setter = Object.getOwnPropertyDescriptor(P.HTMLTextAreaElement.prototype, "value").set;
    setter.call(ta, text);
    ta.dispatchEvent(new P.Event("input", { bubbles: true }));
  }
  function setPlaceholder(text) {
    const ta = getInput();
    if (ta) ta.placeholder = text;
  }
  function sendInput() {
    const send = D.querySelector('button[data-testid="stChatInputSubmitButton"]');
    if (send) send.click();
  }

  // Colocar el botón dentro de la barra de escribir, junto al botón de enviar
  function place() {
    const send = D.querySelector('button[data-testid="stChatInputSubmitButton"]');
    if (send && btn.parentElement !== send.parentElement) {
      send.parentElement.insertBefore(btn, send);
    }
  }
  place();
  setInterval(place, 400);   // por si Streamlit redibuja la barra

  if (!SR) {
    btn.disabled = true;
    btn.title = "Tu navegador no soporta dictado. Usa Chrome o Edge.";
    return;
  }

  const rec = new SR();
  rec.lang = LANG;
  rec.continuous = true;
  rec.interimResults = true;

  let listening = false;
  let finalText = "";
  const defaultPlaceholder = "Escribe o dicta tu duda aquí...";

  rec.onstart = () => {
    listening = true;
    btn.classList.add("on");
    btn.title = "Detener dictado";
    setPlaceholder("🔴 Escuchando... habla ahora");
  };

  rec.onresult = (event) => {
    let interim = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const t = event.results[i][0].transcript;
      if (event.results[i].isFinal) finalText += t + " ";
      else interim += t;
    }
    setInput((finalText + interim).trim());   // escritura en tiempo real
  };

  rec.onerror = (e) => {
    setPlaceholder(e.error === "not-allowed"
      ? "⚠️ Permite el micrófono en el navegador"
      : "⚠️ Error de voz: " + e.error);
  };

  rec.onend = () => {
    listening = false;
    btn.classList.remove("on");
    btn.title = "Dictar por voz";
    setPlaceholder(defaultPlaceholder);
    const text = finalText.trim();
    if (AUTO_SEND && text) setTimeout(sendInput, 350);
    finalText = "";
  };

  btn.onclick = () => {
    if (listening) { rec.stop(); }
    else { finalText = ""; setInput(""); try { rec.start(); } catch (e) {} }
  };
})();
</script>
"""

def voice_dictation(lang: str, auto_send: bool):
    html = (VOICE_HTML
            .replace("__LANG__", lang)
            .replace("__AUTO__", "true" if auto_send else "false"))
    # Streamlit nuevo usa st.iframe; si no existe, usamos el método anterior
    if hasattr(st, "iframe"):
        st.iframe(html, height=1)
    else:
        components.html(html, height=1)

# ==========================================
# 4. BARRA LATERAL (SETTINGS Y HERRAMIENTAS)
# ==========================================

with st.sidebar:
    st.title("🤖 Friday Config")
    st.caption(f"Versión actual: **{APP_VERSION}**")
    st.divider()

    # --- Selección de Modelo y Parámetros ---
    st.subheader("⚙️ Parámetros del Modelo")

    selected_model = st.selectbox(
        "Modelo de Gemini",
        ["gemini-3.6-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
        index=0,
        help="Modelos disponibles. Se mantendrá actualizado para versiones v4.0."
    )

    tutor_mode = st.selectbox(
        "Modo de Tutoría",
        list(SYSTEM_PROMPTS.keys()),
        index=0
    )

    temperature = st.slider(
        "Creatividad (Temperatura)",
        min_value=0.0,
        max_value=1.0,
        value=0.7,
        step=0.1,
        help="0.0 es más preciso y estructurado; 1.0 es más creativo."
    )

    st.divider()

    # --- NUEVO: Opciones de voz ---
    st.subheader("🎤 Dictado por voz")

    voice_lang_label = st.selectbox(
        "Idioma de dictado",
        ["Español (El Salvador)", "Español (España)", "Español (México)", "English (US)"],
        index=0
    )
    VOICE_LANGS = {
        "Español (El Salvador)": "es-SV",
        "Español (España)": "es-ES",
        "Español (México)": "es-MX",
        "English (US)": "en-US",
    }
    voice_lang = VOICE_LANGS[voice_lang_label]

    auto_send = st.checkbox(
        "Enviar automáticamente al terminar de hablar",
        value=True,
        help="Si lo desactivas, el texto dictado queda en la caja para que lo revises y envíes tú."
    )

    show_steps = st.checkbox(
        "Mostrar lo que Friday está haciendo",
        value=True,
        help="Muestra los pasos mientras prepara la respuesta."
    )

    st.divider()

    # --- Gestión del Chat ---
    st.subheader("🛠️ Acciones")

    col_clear, col_export = st.columns(2)

    with col_clear:
        if st.button("🗑️ Limpiar", use_container_width=True):
            st.session_state.messages = []
            st.rerun()

    # --- Métricas ---
    msg_count = len(st.session_state.get("messages", []))
    st.metric("Mensajes en sesión", msg_count)

    # Exportación del Chat
    if msg_count > 0:
        chat_export_data = json.dumps(st.session_state.get("messages", []), indent=2, ensure_ascii=False)
        st.download_button(
            label="📥 Exportar Chat (.json)",
            data=chat_export_data,
            file_name="historial_friday_v3.json",
            mime="application/json",
            use_container_width=True
        )

# ==========================================
# 5. INICIALIZACIÓN DEL MODELO CACHEADO
# ==========================================

@st.cache_resource
def get_llm(model_name: str, temp: float):
    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=API_KEY,
        temperature=temp,
        streaming=True,
        timeout=60,
        max_retries=2
    )

llm = get_llm(selected_model, temperature)

# ==========================================
# 6. ENCABEZADO Y ESTADO INICIAL
# ==========================================

st.title("🤖 Friday, tu tutora virtual")
st.caption("Tu asistente interactivo para aprender, programar y resolver dudas.")

if "messages" not in st.session_state:
    st.session_state.messages = []

# Mensaje de bienvenida inicial si el chat está vacío
if len(st.session_state.messages) == 0:
    welcome_msg = "¡Hola! Soy **Friday**, tu tutora virtual. ¿En qué tema o proyecto te gustaría trabajar hoy?"
    st.session_state.messages.append({"role": "assistant", "content": welcome_msg})

# ==========================================
# 7. RENDERIZAR HISTORIAL DE MENSAJES
# ==========================================

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# ==========================================
# 7.1 NUEVO: BOTÓN DE DICTADO (sobre la caja de chat)
# ==========================================

voice_dictation(voice_lang, auto_send)

# ==========================================
# 8. ENTRADA Y PROCESAMIENTO DE MENSAJES
# ==========================================

if prompt := st.chat_input("Escribe o dicta tu duda aquí..."):

    # 1. Guardar y renderizar mensaje del usuario
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 2. Construir el historial para LangChain
    active_system_prompt = SYSTEM_PROMPTS[tutor_mode]
    if KNOWLEDGE:
        active_system_prompt += (
            "\n\nINFORMACIÓN DE REFERENCIA (úsala cuando sea relevante y "
            "tenla por más confiable que tu memoria):\n" + KNOWLEDGE
        )
    history = [SystemMessage(content=active_system_prompt)]

    for message in st.session_state.messages:
        if message["role"] == "user":
            history.append(HumanMessage(content=message["content"]))
        elif message["role"] == "assistant":
            history.append(AIMessage(content=message["content"]))

    # 3. Generar respuesta streaming CON ESTADO VISIBLE
    with st.chat_message("assistant"):
        status_box = None
        if show_steps:
            status_box = st.status("🧠 Friday está pensando...", expanded=True)
            # Pasos previos a la respuesta (variables según la pregunta)
            for step in get_status_steps(tutor_mode, prompt)[:-1]:
                status_box.update(label=step, state="running")
                status_box.write(step)
                time.sleep(0.6)

        response_placeholder = st.empty()
        full_response = ""

        try:
            if status_box:
                status_box.update(label="✍️ Escribiendo la respuesta...", state="running")
                status_box.write("✍️ Escribiendo la respuesta...")

            for chunk in llm.stream(history):
                text = ""

                # Manejo seguro del contenido según tipo de estructura retornada
                if isinstance(chunk.content, list):
                    for part in chunk.content:
                        if isinstance(part, dict) and "text" in part:
                            text += part["text"]
                        elif isinstance(part, str):
                            text += part
                else:
                    text = str(chunk.content)

                full_response += text
                response_placeholder.markdown(full_response + "▌")

            # Si el modelo no devolvió texto (p. ej. bloqueó el tema), avisar en vez de quedarse mudo
            if not full_response.strip():
                full_response = (
                    "🤔 No pude generar una respuesta para eso. "
                    "Puede ser que el tema esté restringido (por ejemplo, letras completas de canciones). "
                    "¿Probamos reformulando la pregunta?"
                )

            # Renderizado final limpio sin cursor
            response_placeholder.markdown(full_response)

            if status_box:
                status_box.update(label="✅ Respuesta lista", state="complete", expanded=False)

        except Exception as e:
            full_response = (
                "😅 Ups, ocurrió un inconveniente al generar la respuesta.\n\n"
                f"**Detalles técnicos:** `{e}`"
            )
            if status_box:
                status_box.update(label="❌ Ocurrió un error", state="error", expanded=True)
            st.error(full_response)

    # 4. Guardar respuesta del asistente en el historial
    st.session_state.messages.append({"role": "assistant", "content": full_response})
    st.error(full_response)
    # 4. Guardar respuesta del asistente en el historial
    st.session_state.messages.append({"role": "assistant", "content": full_response})

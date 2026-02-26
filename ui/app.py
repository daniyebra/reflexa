"""
Reflexa — Streamlit frontend.

Start the backend first:
    uvicorn reflexa.api.main:app --reload

Then run this app:
    streamlit run ui/app.py
"""
import os
import time

import httpx
import streamlit as st

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")

LANGUAGES: dict[str, str] = {
    "Spanish":    "es",
    "French":     "fr",
    "Portuguese": "pt",
    "Italian":    "it",
    "German":     "de",
    "Japanese":   "ja",
}

PROFICIENCY_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]

# Solid accent colors for error type badges — readable on any background
TYPE_BADGE_COLOR: dict[str, str] = {
    "grammar":    "#3b82f6",
    "vocabulary": "#f97316",
    "spelling":   "#ef4444",
    "syntax":     "#8b5cf6",
    "other":      "#6b7280",
}

LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "logo.png")


@st.cache_resource
def _load_logo():
    """Load logo with white background removed. Cached for the app lifetime."""
    if not os.path.exists(LOGO_PATH):
        return None
    try:
        from PIL import Image
        import numpy as np
        img = Image.open(LOGO_PATH).convert("RGBA")
        arr = np.array(img)
        white = (arr[:, :, 0] > 240) & (arr[:, :, 1] > 240) & (arr[:, :, 2] > 240)
        arr[white, 3] = 0
        return Image.fromarray(arr)
    except Exception:
        return None


def _type_badge(error_type: str) -> str:
    """Outline pill badge — readable in both light and dark mode."""
    color = TYPE_BADGE_COLOR.get(error_type, "#6b7280")
    return (
        f'<span style="border:1.5px solid {color};color:{color};'
        f'padding:1px 9px;border-radius:12px;font-size:0.78em;font-weight:600;'
        f'text-transform:capitalize;white-space:nowrap">{error_type}</span>'
    )


def _section_label(text: str) -> str:
    """Small uppercase section label — uses opacity so it adapts to any theme."""
    return (
        f'<p style="font-size:0.75em;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.06em;opacity:0.45;margin:14px 0 4px 0">{text}</p>'
    )


# ---------------------------------------------------------------------------
# API helpers (synchronous — Streamlit is synchronous by default)
# ---------------------------------------------------------------------------

def _post(path: str, payload: dict, _retries: int = 3) -> dict:
    url = f"{BACKEND_URL}{path}"
    for attempt in range(_retries + 1):
        try:
            r = httpx.post(url, json=payload, timeout=60)
            r.raise_for_status()
            return r.json()
        except httpx.ConnectError:
            if attempt < _retries:
                time.sleep(2)
                continue
            st.error(
                f"Cannot reach backend at `{BACKEND_URL}`. "
                "Start it with: `uvicorn reflexa.api.main:app --reload`"
            )
            st.stop()
        except httpx.HTTPStatusError as exc:
            st.error(f"API error {exc.response.status_code}: {exc.response.text}")
            st.stop()


def api_create_session(target_language: str, proficiency_level: str | None) -> dict:
    payload: dict = {"target_language": target_language}
    if proficiency_level:
        payload["proficiency_level"] = proficiency_level
    return _post("/sessions", payload)


def api_create_turn(session_id: str, user_message: str) -> dict:
    return _post(f"/sessions/{session_id}/turns", {"user_message": user_message})


# ---------------------------------------------------------------------------
# Feedback renderer
# ---------------------------------------------------------------------------

def render_feedback(fb: dict) -> None:
    """Render a FeedbackResponse dict as structured Streamlit components."""

    # ── Corrected utterance ──────────────────────────────────────────────
    st.markdown(_section_label("Corrected utterance"), unsafe_allow_html=True)
    st.success(fb["corrected_utterance"])

    # ── Error list ───────────────────────────────────────────────────────
    st.markdown(_section_label("Errors identified"), unsafe_allow_html=True)
    errors = fb.get("error_list", [])
    if errors:
        for err in errors:
            badge = _type_badge(err["type"])
            st.markdown(
                f'{badge} &nbsp;<code>{err["span"]}</code> — {err["description"]}',
                unsafe_allow_html=True,
            )
    else:
        st.markdown("✅ No errors found.")

    # ── Explanations ─────────────────────────────────────────────────────
    st.markdown(_section_label("Explanations"), unsafe_allow_html=True)
    st.write(fb["explanations"])

    # ── Prioritization & focus ───────────────────────────────────────────
    st.markdown(_section_label("Prioritisation & focus"), unsafe_allow_html=True)
    st.info(fb["prioritization_and_focus"])

    # ── Practice prompt ──────────────────────────────────────────────────
    # Semi-transparent background so it reads correctly in light and dark mode.
    st.markdown(
        f"""
<div style="
    background: rgba(59, 130, 246, 0.08);
    border-left: 4px solid #3b82f6;
    border-radius: 6px;
    padding: 14px 18px;
    margin-top: 10px;
    line-height: 1.6;
">
  <div style="font-size:0.75em;font-weight:700;text-transform:uppercase;
              letter-spacing:0.06em;color:#3b82f6;margin-bottom:6px">
    ✏️ Practice prompt
  </div>
  {fb['practice_prompt']}
</div>
""",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar() -> None:
    with st.sidebar:
        logo = _load_logo()
        if logo is not None:
            st.image(logo, width=200)
            st.markdown("")
        else:
            st.markdown("## 🗣️ Reflexa")

        st.caption("Language learning feedback research platform")
        st.divider()

        if "session_id" not in st.session_state:
            # ── Setup form ───────────────────────────────────────────────
            st.subheader("New Session")

            lang_name = st.selectbox("Target language", list(LANGUAGES.keys()), index=0)
            level = st.selectbox("Proficiency level", PROFICIENCY_LEVELS, index=2)  # B1

            if st.button("Start Session", type="primary", use_container_width=True):
                with st.spinner("Creating session…"):
                    data = api_create_session(LANGUAGES[lang_name], level)
                st.session_state.session_id        = data["id"]
                st.session_state.target_language   = lang_name
                st.session_state.proficiency_level = level
                st.session_state.turn_count        = 0
                st.session_state.last_latency_ms   = None
                st.session_state.messages          = []
                st.session_state.opener_message    = data.get("opener_message")
                st.rerun()

        else:
            # ── Session info ─────────────────────────────────────────────
            sid = st.session_state.session_id
            st.subheader("Active Session")

            st.markdown(
                f"""
| | |
|---|---|
| **ID** | `{sid[:8]}…` |
| **Language** | {st.session_state.target_language} |
| **Level** | {st.session_state.proficiency_level} |
| **Turns** | {st.session_state.turn_count} |
""")

            if st.session_state.last_latency_ms is not None:
                st.caption(f"Last response: {st.session_state.last_latency_ms} ms")

            st.divider()
            if st.button("End Session", use_container_width=True):
                for key in ("session_id", "target_language", "proficiency_level",
                            "turn_count", "last_latency_ms", "messages", "opener_message"):
                    st.session_state.pop(key, None)
                st.rerun()


# ---------------------------------------------------------------------------
# Main chat view
# ---------------------------------------------------------------------------

def render_turn(msg: dict) -> None:
    """Render a stored turn: user bubble, reply bubble, collapsed feedback."""
    fb = msg["feedback"]
    with st.chat_message("user"):
        st.write(msg["user_message"])
    with st.chat_message("assistant"):
        reply = fb.get("conversation_reply", "")
        if reply:
            st.write(reply)
        with st.expander("📝 Feedback"):
            render_feedback(fb)


def render_chat() -> None:
    st.title("Reflexa")
    st.caption("AI-powered language feedback research platform")

    if "session_id" not in st.session_state:
        st.info("Configure a session in the sidebar to get started.")
        return

    # Opener bubble (first assistant message before any user turn)
    opener = st.session_state.get("opener_message")
    if opener:
        with st.chat_message("assistant"):
            st.write(opener)

    # Replay history
    for msg in st.session_state.messages:
        render_turn(msg)

    # Chat input
    user_input = st.chat_input(
        f"Write in {st.session_state.target_language}…",
        max_chars=2000,
    )

    if user_input:
        with st.chat_message("user"):
            st.write(user_input)

        with st.chat_message("assistant"):
            with st.spinner("Analysing…"):
                data = api_create_turn(st.session_state.session_id, user_input)

            fb = data["feedback"]
            reply = fb.get("conversation_reply", "")
            if reply:
                st.write(reply)
            with st.expander("📝 Feedback"):
                render_feedback(fb)

        st.session_state.messages.append({
            "user_message": user_input,
            "feedback": fb,
        })
        st.session_state.turn_count      = data["turn_index"] + 1
        st.session_state.last_latency_ms = fb["latency_ms"]
        st.rerun()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Reflexa",
    page_icon="🗣️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
footer {visibility: hidden;}
[data-testid="stExpander"] {
    border: 1px solid rgba(128, 128, 128, 0.2);
    border-radius: 8px;
}
.main .block-container {
    padding-top: 1.5rem;
}
</style>
""", unsafe_allow_html=True)

render_sidebar()
render_chat()

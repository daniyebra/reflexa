"""
Reflexa — Streamlit frontend.

Start the backend first:
    uvicorn reflexa.api.main:app --reload

Then run this app:
    streamlit run ui/app.py
"""
import os

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
}

PROFICIENCY_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]

TYPE_BADGE: dict[str, str] = {
    "grammar":    "🔵",
    "vocabulary": "🟠",
    "spelling":   "🔴",
    "syntax":     "🟣",
    "other":      "⚪",
}

# ---------------------------------------------------------------------------
# API helpers (synchronous — Streamlit is synchronous by default)
# ---------------------------------------------------------------------------

def _post(path: str, payload: dict) -> dict:
    url = f"{BACKEND_URL}{path}"
    try:
        r = httpx.post(url, json=payload, timeout=60)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
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
    st.markdown("**Corrected utterance**")
    st.success(fb["corrected_utterance"])

    # ── Error list ───────────────────────────────────────────────────────
    errors = fb.get("error_list", [])
    if errors:
        st.markdown("**Errors identified**")
        for err in errors:
            badge = TYPE_BADGE.get(err["type"], "⚪")
            st.markdown(
                f"{badge} `{err['span']}` — **{err['type']}**: {err['description']}"
            )
    else:
        st.markdown("✅ No errors found.")

    # ── Explanations ─────────────────────────────────────────────────────
    st.markdown("**📖 Explanations**")
    st.write(fb["explanations"])

    # ── Prioritization & focus ───────────────────────────────────────────
    st.info(f"🎯 **Prioritisation & Focus**\n\n{fb['prioritization_and_focus']}")

    # ── Practice prompt ──────────────────────────────────────────────────
    st.markdown(
        f"""
<div style="
    background: #f0f4ff;
    border-left: 4px solid #4a6fa5;
    border-radius: 4px;
    padding: 12px 16px;
    margin-top: 8px;
">
<strong>✏️ Practice prompt</strong><br>{fb['practice_prompt']}
</div>
""",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar() -> None:
    with st.sidebar:
        st.title("Reflexa")
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
                st.session_state.session_id       = data["id"]
                st.session_state.target_language  = lang_name
                st.session_state.proficiency_level = level
                st.session_state.turn_count       = 0
                st.session_state.last_latency_ms  = None
                st.session_state.messages         = []
                st.session_state.opener_message   = data.get("opener_message")
                st.rerun()

        else:
            # ── Session info ─────────────────────────────────────────────
            sid = st.session_state.session_id
            st.subheader("Session")
            st.markdown(f"**ID** `{sid[:8]}…`")
            st.markdown(f"**Language** {st.session_state.target_language}")
            st.markdown(f"**Level** {st.session_state.proficiency_level}")
            st.markdown(f"**Turns** {st.session_state.turn_count}")
            st.markdown("**Condition shown** Baseline")
            if st.session_state.last_latency_ms is not None:
                st.markdown(f"**Last latency** {st.session_state.last_latency_ms} ms")

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
        # Primary: conversation reply
        reply = fb.get("conversation_reply", "")
        if reply:
            st.write(reply)
        # Structured feedback collapsed below
        with st.expander("📝 Feedback"):
            render_feedback(fb)


def render_chat() -> None:
    st.title("Reflexa — Language Feedback")

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
        # Show user message immediately
        with st.chat_message("user"):
            st.write(user_input)

        # Call API
        with st.chat_message("assistant"):
            with st.spinner("Analysing…"):
                data = api_create_turn(st.session_state.session_id, user_input)

            fb = data["feedback"]
            reply = fb.get("conversation_reply", "")
            if reply:
                st.write(reply)
            with st.expander("📝 Feedback"):
                render_feedback(fb)

        # Persist to session state
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

render_sidebar()
render_chat()

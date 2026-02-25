from sqlalchemy.ext.asyncio import AsyncSession

from reflexa.db import crud


class ConversationMemory:
    def __init__(self, max_turns: int) -> None:
        self.max_turns = max_turns

    async def get_history(
        self,
        db: AsyncSession,
        session_id: str,
        display_condition: str,
    ) -> list[dict]:
        """
        Return an OpenAI-style message list for the last max_turns turns.
        Only the display-condition corrected utterance is used as the
        assistant turn (prevents cross-condition contamination).
        """
        turns = await crud.get_recent_turns(db, session_id, self.max_turns)
        history: list[dict] = []
        for turn in turns:
            history.append({"role": "user", "content": turn.user_message})
            fo = await crud.get_feedback_output(db, turn.id, display_condition)
            if fo:
                history.append({"role": "assistant", "content": fo.corrected_utterance})
                if fo.conversation_reply:
                    history.append({"role": "assistant", "content": fo.conversation_reply})
        return history

    @staticmethod
    def format_for_prompt(history: list[dict]) -> str:
        """Render the history list as a plain-text string for prompt injection."""
        if not history:
            return "(no prior conversation)"
        lines = []
        for msg in history:
            role = "Student" if msg["role"] == "user" else "Teacher"
            lines.append(f"{role}: {msg['content']}")
        return "\n".join(lines)

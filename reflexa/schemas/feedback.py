from pydantic import BaseModel


class ErrorItem(BaseModel):
    span: str           # quoted substring from the original student message
    description: str    # brief explanation of what is wrong
    type: str           # "grammar" | "vocabulary" | "spelling" | "syntax" | "other"


class FeedbackOutput(BaseModel):
    corrected_utterance: str
    error_list: list[ErrorItem]
    explanations: str
    prioritization_and_focus: str
    practice_prompt: str
    conversation_reply: str = ""

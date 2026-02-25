from pydantic import BaseModel


class VerifierOutput(BaseModel):
    issues: list[str]         # inaccuracies / hallucinations found in the draft
    missed_errors: list[str]  # real errors the draft overlooked
    verdict: str              # "pass" | "revise"


class CriticOutput(BaseModel):
    critique: list[str]       # pedagogical weaknesses
    suggestions: list[str]    # concrete improvements
    verdict: str              # "pass" | "revise"


# ---------------------------------------------------------------------------
# Register mock data so MockLLMClient can return these types
# ---------------------------------------------------------------------------

def _register_mocks() -> None:
    from reflexa.llm.mock import _register

    _register(VerifierOutput, {
        "issues": [],
        "missed_errors": [],
        "verdict": "pass",
    })
    _register(CriticOutput, {
        "critique": [],
        "suggestions": [],
        "verdict": "pass",
    })


_register_mocks()

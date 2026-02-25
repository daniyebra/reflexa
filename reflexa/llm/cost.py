"""
Per-model token cost table.

Costs are in USD per 1 million tokens (input / output).
Update this table as OpenAI revises pricing.
"""

# (input_cost_per_1M, output_cost_per_1M) in USD
_COSTS: dict[str, tuple[float, float]] = {
    "gpt-4o":              (2.50,  10.00),
    "gpt-4o-mini":         (0.15,   0.60),
    "gpt-4-turbo":        (10.00,  30.00),
    "gpt-4":              (30.00,  60.00),
    "gpt-3.5-turbo":       (0.50,   1.50),
    "o1":                 (15.00,  60.00),
    "o1-mini":             (3.00,  12.00),
    "o3-mini":             (1.10,   4.40),
}


def estimate_cost(model_id: str, tokens_in: int, tokens_out: int) -> float | None:
    """Return estimated USD cost for an LLM call, or None if model is unknown."""
    entry = _COSTS.get(model_id)
    if entry is None:
        return None
    input_rate, output_rate = entry
    return (tokens_in * input_rate + tokens_out * output_rate) / 1_000_000

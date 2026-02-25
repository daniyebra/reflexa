"""
Phase 1 tests — PromptLoader and versioned YAML prompts.
"""
import pytest

from reflexa.prompt_loader import PromptLoader, PromptTemplate, get_prompt, PROMPTS_DIR

# Use the real prompts directory so we test the actual YAML files
_loader = PromptLoader(PROMPTS_DIR)

EXPECTED_NAMES = {
    "baseline",
    "pipeline_draft",
    "pipeline_verifier",
    "pipeline_critic",
    "pipeline_reviser",
    "eval_judge",
    "session_opener",
}

# Maps name → expected latest version suffix (e.g. "v2" for baseline)
_EXPECTED_LATEST: dict[str, str] = {
    "baseline":           "v2",
    "pipeline_draft":     "v1",
    "pipeline_verifier":  "v1",
    "pipeline_critic":    "v1",
    "pipeline_reviser":   "v2",
    "eval_judge":         "v1",
    "session_opener":     "v1",
}


# ---------------------------------------------------------------------------
# Version resolution
# ---------------------------------------------------------------------------

def test_latest_baseline_version_id():
    assert _loader.latest("baseline").version_id == "baseline/v2"


def test_latest_all_names():
    for name in EXPECTED_NAMES:
        tmpl = _loader.latest(name)
        assert tmpl.version_id.startswith(f"{name}/v")


def test_get_by_exact_version_id():
    tmpl = _loader.get("baseline/v1")
    assert tmpl.version_id == "baseline/v1"


def test_get_unknown_version_raises_key_error():
    with pytest.raises(KeyError):
        _loader.get("baseline/v999")


def test_latest_unknown_name_raises_key_error():
    with pytest.raises(KeyError):
        _loader.latest("nonexistent_prompt_name")


# ---------------------------------------------------------------------------
# All six prompt names must be present
# ---------------------------------------------------------------------------

def test_all_names_present():
    assert EXPECTED_NAMES == set(_loader._by_name.keys())


def test_all_v1_version_ids_present():
    for name in EXPECTED_NAMES:
        assert f"{name}/v1" in _loader._by_version


# ---------------------------------------------------------------------------
# Required YAML fields
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(EXPECTED_NAMES))
def test_version_id_field(name):
    tmpl = _loader.latest(name)
    expected_version = _EXPECTED_LATEST[name]
    assert tmpl.version_id == f"{name}/{expected_version}"


@pytest.mark.parametrize("name", sorted(EXPECTED_NAMES))
def test_description_nonempty(name):
    assert _loader.latest(name).description.strip()


@pytest.mark.parametrize("name", sorted(EXPECTED_NAMES))
def test_created_at_present(name):
    assert _loader.latest(name).created_at


@pytest.mark.parametrize("name", sorted(EXPECTED_NAMES))
def test_model_constraints_has_temperature(name):
    assert "temperature" in _loader.latest(name).model_constraints


@pytest.mark.parametrize("name", sorted(EXPECTED_NAMES))
def test_model_constraints_has_max_tokens(name):
    assert "max_tokens" in _loader.latest(name).model_constraints


@pytest.mark.parametrize("name", sorted(EXPECTED_NAMES))
def test_system_prompt_nonempty(name):
    assert _loader.latest(name).system.strip()


@pytest.mark.parametrize("name", sorted(EXPECTED_NAMES))
def test_user_template_nonempty(name):
    assert _loader.latest(name).user_template.strip()


# ---------------------------------------------------------------------------
# PromptTemplate render helpers
# ---------------------------------------------------------------------------

def test_render_system_substitutes_variables():
    tmpl = _loader.latest("baseline")
    rendered = tmpl.render_system(
        target_language="Spanish",
        proficiency_level="B1",
    )
    assert "Spanish" in rendered
    assert "B1" in rendered
    assert "{target_language}" not in rendered
    assert "{proficiency_level}" not in rendered


def test_render_user_substitutes_variables():
    tmpl = _loader.latest("baseline")
    rendered = tmpl.render_user(
        user_message="Yo fui al mercado.",
        conversation_history="",
    )
    assert "Yo fui al mercado." in rendered
    assert "{user_message}" not in rendered


def test_to_messages_returns_two_items():
    tmpl = _loader.latest("baseline")
    msgs = tmpl.to_messages(
        target_language="Spanish",
        proficiency_level="B1",
        user_message="Hola.",
        conversation_history="",
    )
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"


# ---------------------------------------------------------------------------
# get_prompt() — env-var override path (no override set in test env)
# ---------------------------------------------------------------------------

def test_get_prompt_returns_latest_by_default():
    tmpl = get_prompt("baseline")
    assert tmpl.version_id == "baseline/v2"


def test_get_prompt_returns_prompt_template_instance():
    assert isinstance(get_prompt("eval_judge"), PromptTemplate)


# ---------------------------------------------------------------------------
# model_constraints value types
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(EXPECTED_NAMES))
def test_temperature_is_float(name):
    temp = _loader.latest(name).model_constraints["temperature"]
    assert isinstance(temp, (int, float))
    assert 0.0 <= temp <= 2.0


@pytest.mark.parametrize("name", sorted(EXPECTED_NAMES))
def test_max_tokens_is_positive_int(name):
    mt = _loader.latest(name).model_constraints["max_tokens"]
    assert isinstance(mt, int)
    assert mt > 0

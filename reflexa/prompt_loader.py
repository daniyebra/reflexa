"""
Versioned prompt loader.

Prompt files live at reflexa/prompts/{name}/v{N}.yaml and are IMMUTABLE
once committed.  To modify a prompt, create v{N+1}.yaml — never edit in place.

Usage:
    from reflexa.prompt_loader import get_prompt, loader

    tmpl = get_prompt("baseline")          # respects env-var override, else latest
    tmpl = loader.get("baseline/v1")       # exact version
    tmpl = loader.latest("baseline")       # highest vN for that name
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True)
class PromptTemplate:
    version_id: str          # e.g. "baseline/v1"
    description: str
    created_at: str          # ISO date string
    model_constraints: dict[str, Any]   # temperature, max_tokens, …
    system: str              # system prompt (may contain {variable} placeholders)
    user_template: str       # user turn template (may contain {variable} placeholders)

    def render_system(self, **kwargs: Any) -> str:
        """Substitute {variable} placeholders in the system prompt."""
        return self.system.format_map(kwargs)

    def render_user(self, **kwargs: Any) -> str:
        """Substitute {variable} placeholders in the user template."""
        return self.user_template.format_map(kwargs)

    def to_messages(self, **kwargs: Any) -> list[dict[str, str]]:
        """Render both parts and return an OpenAI-style messages list."""
        return [
            {"role": "system", "content": self.render_system(**kwargs)},
            {"role": "user",   "content": self.render_user(**kwargs)},
        ]


_VERSION_RE = re.compile(r"^v(\d+)$")


class PromptLoader:
    """Loads and caches all prompt YAML files from a prompts directory."""

    def __init__(self, prompts_dir: Path = PROMPTS_DIR) -> None:
        self._by_version: dict[str, PromptTemplate] = {}
        # name → sorted list of (version_number, PromptTemplate)
        self._by_name: dict[str, list[tuple[int, PromptTemplate]]] = {}
        self._load(prompts_dir)

    def _load(self, prompts_dir: Path) -> None:
        for yaml_path in sorted(prompts_dir.glob("**/*.yaml")):
            with yaml_path.open(encoding="utf-8") as fh:
                data = yaml.safe_load(fh)

            tmpl = PromptTemplate(
                version_id=data["version_id"],
                description=data["description"],
                created_at=data["created_at"],
                model_constraints=data.get("model_constraints", {}),
                system=data["system"],
                user_template=data["user_template"],
            )
            self._by_version[tmpl.version_id] = tmpl

            # version_id format: "{name}/v{N}"
            name, v_str = tmpl.version_id.rsplit("/", 1)
            m = _VERSION_RE.match(v_str)
            if m is None:
                raise ValueError(f"Malformed version string in {yaml_path}: {v_str!r}")
            n = int(m.group(1))
            self._by_name.setdefault(name, []).append((n, tmpl))

        # Sort each name's list by version number ascending
        for name in self._by_name:
            self._by_name[name].sort(key=lambda x: x[0])

    def get(self, version_id: str) -> PromptTemplate:
        """Return the prompt for an exact version_id (e.g. 'baseline/v1')."""
        if version_id not in self._by_version:
            raise KeyError(f"Prompt version not found: {version_id!r}")
        return self._by_version[version_id]

    def latest(self, name: str) -> PromptTemplate:
        """Return the highest-versioned prompt for a given name."""
        if name not in self._by_name:
            raise KeyError(f"No prompts found for name: {name!r}")
        return self._by_name[name][-1][1]


# ---------------------------------------------------------------------------
# Module-level singleton (initialised once at import time)
# ---------------------------------------------------------------------------

loader = PromptLoader()


def get_prompt(name: str) -> PromptTemplate:
    """
    Return the active prompt for a pipeline stage.

    Checks the corresponding env-var override first (e.g. BASELINE_PROMPT_VERSION);
    falls back to the latest version if the var is unset or empty.
    """
    from reflexa.config import settings  # local import avoids circular dependency at module level

    _overrides: dict[str, str] = {
        "baseline":           settings.baseline_prompt_version,
        "pipeline_draft":     settings.pipeline_draft_prompt_version,
        "pipeline_verifier":  settings.pipeline_verifier_prompt_version,
        "pipeline_critic":    settings.pipeline_critic_prompt_version,
        "pipeline_reviser":   settings.pipeline_reviser_prompt_version,
        "eval_judge":         settings.eval_judge_prompt_version,
        "session_opener":     settings.session_opener_prompt_version,
    }

    override = _overrides.get(name, "")
    if override:
        return loader.get(override)
    return loader.latest(name)

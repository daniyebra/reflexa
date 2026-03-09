"""
CLI — simulate realistic user sessions by generating learner messages with Claude.

Uses Claude via OpenRouter to roleplay as language learners with varied L1 backgrounds,
proficiency levels, and interests. Sends generated messages to the deployed Reflexa API
to create sessions and turns with real pipeline outputs.

Usage:
    python scripts/simulate_sessions.py --dry-run
    python scripts/simulate_sessions.py --sessions 2 --turns-per-session 3
    python scripts/simulate_sessions.py --sessions 20 --turns-per-session 10
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx
from openai import AsyncOpenAI

# ---------------------------------------------------------------------------
# Learner personas — 20 diverse profiles
# ---------------------------------------------------------------------------

PERSONAS = [
    # Spanish (6)
    {"name": "Sarah", "age": 28, "native_language": "English", "target_language": "es",
     "proficiency_level": "A1", "interests": "cooking, travel",
     "personality": "enthusiastic but nervous about making mistakes"},
    {"name": "Wei", "age": 34, "native_language": "Mandarin", "target_language": "es",
     "proficiency_level": "A2", "interests": "soccer, movies",
     "personality": "quiet and methodical, prefers short sentences"},
    {"name": "Fatima", "age": 22, "native_language": "Arabic", "target_language": "es",
     "proficiency_level": "B1", "interests": "music, social media, fashion",
     "personality": "chatty and expressive, uses filler words"},
    {"name": "Kenji", "age": 41, "native_language": "Japanese", "target_language": "es",
     "proficiency_level": "B1", "interests": "business, wine, history",
     "personality": "formal and polite, sometimes overly so"},
    {"name": "Priya", "age": 25, "native_language": "Hindi", "target_language": "es",
     "proficiency_level": "B2", "interests": "yoga, vegetarian cooking, Bollywood",
     "personality": "confident but occasionally mixes up gender agreements"},
    {"name": "Olga", "age": 38, "native_language": "Russian", "target_language": "es",
     "proficiency_level": "C1", "interests": "literature, politics, classical music",
     "personality": "articulate, makes subtle preposition and article errors"},

    # French (4)
    {"name": "Tom", "age": 19, "native_language": "English", "target_language": "fr",
     "proficiency_level": "A1", "interests": "video games, skateboarding",
     "personality": "casual, uses slang attempts, sometimes code-switches to English"},
    {"name": "Min-ji", "age": 30, "native_language": "Korean", "target_language": "fr",
     "proficiency_level": "A2", "interests": "K-beauty, photography, cafes",
     "personality": "shy, writes carefully but struggles with verb conjugation"},
    {"name": "Carlos", "age": 27, "native_language": "Portuguese", "target_language": "fr",
     "proficiency_level": "B1", "interests": "surfing, environmental activism",
     "personality": "relies on Portuguese-French cognates, sometimes false friends"},
    {"name": "Ahmed", "age": 45, "native_language": "Arabic", "target_language": "fr",
     "proficiency_level": "B2", "interests": "architecture, philosophy, chess",
     "personality": "thoughtful, writes long sentences with occasional agreement errors"},

    # German (3)
    {"name": "Lucy", "age": 23, "native_language": "English", "target_language": "de",
     "proficiency_level": "A2", "interests": "hiking, board games, craft beer",
     "personality": "playful, guesses at word order and often gets it wrong"},
    {"name": "Yuki", "age": 29, "native_language": "Japanese", "target_language": "de",
     "proficiency_level": "B1", "interests": "engineering, anime, cycling",
     "personality": "precise but struggles with articles (der/die/das)"},
    {"name": "Sofia", "age": 35, "native_language": "Spanish", "target_language": "de",
     "proficiency_level": "B2", "interests": "dance, psychology, children's education",
     "personality": "expressive, struggles with Konjunktiv II and long compound words"},

    # Portuguese (3)
    {"name": "James", "age": 31, "native_language": "English", "target_language": "pt",
     "proficiency_level": "A1", "interests": "martial arts, podcasts",
     "personality": "eager, tries complex ideas with simple vocabulary"},
    {"name": "Soo-yeon", "age": 26, "native_language": "Korean", "target_language": "pt",
     "proficiency_level": "A2", "interests": "K-drama, baking, cats",
     "personality": "careful writer, sometimes forgets accents and tildes"},
    {"name": "Hans", "age": 50, "native_language": "German", "target_language": "pt",
     "proficiency_level": "B1", "interests": "sailing, wine tasting, retirement planning",
     "personality": "structured, writes grammatically but sounds overly formal"},

    # Italian (2)
    {"name": "Emily", "age": 24, "native_language": "English", "target_language": "it",
     "proficiency_level": "A1", "interests": "art history, pasta making, romance novels",
     "personality": "romantic about Italy, sprinkles in English words she doesn't know"},
    {"name": "Dmitri", "age": 33, "native_language": "Russian", "target_language": "it",
     "proficiency_level": "C1", "interests": "opera, fine dining, architecture",
     "personality": "sophisticated vocabulary but occasional wrong prepositions"},

    # Japanese (2)
    {"name": "Mike", "age": 20, "native_language": "English", "target_language": "ja",
     "proficiency_level": "A1", "interests": "anime, manga, ramen",
     "personality": "uses romaji mixed with hiragana, excited about Japanese culture"},
    {"name": "Lena", "age": 37, "native_language": "German", "target_language": "ja",
     "proficiency_level": "A2", "interests": "tea ceremony, minimalism, calligraphy",
     "personality": "patient and detail-oriented, struggles with particles"},
]

# ---------------------------------------------------------------------------
# Claude prompt for learner simulation
# ---------------------------------------------------------------------------

LEARNER_SYSTEM_PROMPT = """\
You are roleplaying as a real language learner. You are NOT an AI — you are {name}, \
a {age}-year-old {native_language} speaker learning {target_language} at {proficiency_level} level.

Your personality: {personality}
Your interests: {interests}

CRITICAL RULES:
1. Write ONLY in {target_language}. Your response is the message itself — no explanations, \
no meta-commentary, no quotation marks around it.
2. Make REALISTIC mistakes appropriate for a {proficiency_level} {native_language} speaker:
   - L1 transfer errors (word order, false cognates, literal translations from {native_language})
   - Developmental errors typical of {proficiency_level} (wrong conjugations, gender agreement, \
missing accents, wrong prepositions)
   - At A1/A2: occasional code-switching to {native_language} for words you don't know, \
very short sentences, limited vocabulary
   - At B1/B2: longer sentences with some structural errors, wider vocabulary with occasional \
wrong word choices
   - At C1: mostly fluent but with subtle errors in idioms, prepositions, or register
3. Keep your message between 1-4 sentences (appropriate to {proficiency_level}).
4. Respond naturally to what the teacher said — answer their questions, react to their comments.
5. Stay in character. Talk about your interests and life naturally.
6. NEVER write perfectly — you are a LEARNER, not a native speaker.
7. Do NOT add any prefix, label, or explanation. Just write the message as the student would type it."""

LEARNER_USER_PROMPT_FIRST = """\
The teacher just opened the conversation with this greeting:
"{opener_message}"

Write your first response as {name}. Remember you are {proficiency_level} level — \
make appropriate mistakes occassionally, with varying frequency according to your proficiency level. Introduce yourself or respond to the greeting naturally."""

LEARNER_USER_PROMPT_TURN = """\
The teacher responded to your last message with:
"{conversation_reply}"

Write your next message as {name}. Continue the conversation naturally, \
responding to what the teacher said. Remember to make {proficiency_level}-appropriate mistakes. \
This is turn {turn_number} of the conversation — keep the conversation flowing naturally \
and bring up your interests ({interests}) when it fits."""

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
SIMULATOR_MODEL = "anthropic/claude-sonnet-4"


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

async def generate_learner_message(
    client: AsyncOpenAI,
    persona: dict,
    context_message: str,
    turn_number: int,
    is_first: bool,
) -> str:
    """Call Claude via OpenRouter to generate a realistic learner message."""
    system = LEARNER_SYSTEM_PROMPT.format(**persona)
    if is_first:
        user = LEARNER_USER_PROMPT_FIRST.format(
            opener_message=context_message,
            name=persona["name"],
            proficiency_level=persona["proficiency_level"],
        )
    else:
        user = LEARNER_USER_PROMPT_TURN.format(
            conversation_reply=context_message,
            name=persona["name"],
            proficiency_level=persona["proficiency_level"],
            turn_number=turn_number,
            interests=persona["interests"],
        )

    response = await client.chat.completions.create(
        model=SIMULATOR_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.9,
        max_completion_tokens=300,
    )
    return response.choices[0].message.content.strip()


async def create_session(
    http: httpx.AsyncClient,
    api_url: str,
    persona: dict,
) -> tuple[str, str]:
    """POST /sessions → (session_id, opener_message)"""
    resp = await http.post(
        f"{api_url}/sessions",
        json={
            "target_language": persona["target_language"],
            "proficiency_level": persona["proficiency_level"],
        },
    )
    resp.raise_for_status()
    data = resp.json()
    return data["id"], data.get("opener_message", "")


async def send_turn(
    http: httpx.AsyncClient,
    api_url: str,
    session_id: str,
    user_message: str,
    max_retries: int = 5,
) -> dict:
    """POST /sessions/{id}/turns with retry on 500/503 (SQLite locking)."""
    for attempt in range(max_retries):
        resp = await http.post(
            f"{api_url}/sessions/{session_id}/turns",
            json={"user_message": user_message},
        )
        if resp.status_code in (500, 503) and attempt < max_retries - 1:
            wait = 3 * (attempt + 1)
            print(f"    [{resp.status_code}] Retrying in {wait}s (attempt {attempt + 1}/{max_retries})")
            await asyncio.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"Failed after {max_retries} retries")


async def simulate_session(
    llm: AsyncOpenAI,
    http: httpx.AsyncClient,
    api_url: str,
    persona: dict,
    turns_per_session: int,
    delay: float,
    session_index: int,
) -> tuple[int, int]:
    """Simulate one full user session. Returns (turns_completed, failures)."""
    label = f"[{session_index + 1:2d}] {persona['name']:10s} ({persona['target_language']}/{persona['proficiency_level']})"
    try:
        session_id, opener = await create_session(http, api_url, persona)
        print(f"{label}  session={session_id[:8]}…  opener={opener[:50]}…")
    except Exception as exc:
        print(f"{label}  FAILED to create session: {exc}")
        return 0, 1

    context_message = opener
    completed = 0

    for t in range(turns_per_session):
        try:
            msg = await generate_learner_message(
                llm, persona, context_message, turn_number=t + 1, is_first=(t == 0),
            )
            result = await send_turn(http, api_url, session_id, msg)
            reply = result.get("feedback", {}).get("conversation_reply", "")
            context_message = reply or context_message
            completed += 1
            preview = msg[:60].replace("\n", " ")
            print(f"{label}  turn {t + 1:2d}/{turns_per_session}  \"{preview}…\"")
        except Exception as exc:
            print(f"{label}  turn {t + 1:2d}/{turns_per_session}  FAILED: {exc}")

        if t < turns_per_session - 1:
            await asyncio.sleep(delay)

    return completed, 0


async def _run(
    api_url: str,
    openrouter_key: str,
    n_sessions: int,
    turns_per_session: int,
    delay: float,
    dry_run: bool,
) -> None:
    personas = PERSONAS[:n_sessions]

    print(f"Sessions to simulate: {len(personas)}")
    print(f"Turns per session   : {turns_per_session}")
    print(f"Total turns planned : {len(personas) * turns_per_session}")
    print(f"API URL             : {api_url}")
    print(f"Simulator model     : {SIMULATOR_MODEL}")
    print(f"Delay between turns : {delay}s")
    print()

    if dry_run:
        print("=== PERSONAS ===")
        for i, p in enumerate(personas):
            print(f"  {i + 1:2d}. {p['name']:10s} | {p['native_language']:10s} → "
                  f"{p['target_language']} {p['proficiency_level']} | {p['interests']}")
        print()
        print("=== SAMPLE SYSTEM PROMPT ===")
        print(LEARNER_SYSTEM_PROMPT.format(**personas[0]))
        print()
        print("=== SAMPLE USER PROMPT (first turn) ===")
        print(LEARNER_USER_PROMPT_FIRST.format(
            opener_message="¡Hola! ¿Qué hiciste el fin de semana pasado?",
            name=personas[0]["name"],
            proficiency_level=personas[0]["proficiency_level"],
        ))
        print("\n[dry-run] No API calls made.")
        return

    llm = AsyncOpenAI(
        api_key=openrouter_key,
        base_url=OPENROUTER_BASE_URL,
    )

    total_completed = 0
    total_failures = 0
    start = time.monotonic()

    async with httpx.AsyncClient(timeout=60.0) as http:
        for i, persona in enumerate(personas):
            completed, failures = await simulate_session(
                llm, http, api_url, persona,
                turns_per_session, delay, session_index=i,
            )
            total_completed += completed
            total_failures += failures
            print()

    elapsed = time.monotonic() - start

    print("=" * 60)
    print(f"Done in {elapsed:.0f}s")
    print(f"Sessions created : {len(personas) - total_failures}")
    print(f"Turns completed  : {total_completed}")
    print(f"Failures         : {total_failures}")


def _resolve_openrouter_key(cli_key: str | None) -> str:
    """Resolve OpenRouter key from CLI arg, env var, or .env file."""
    if cli_key:
        return cli_key
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"]
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("OPENROUTER_API_KEY=") and not line.startswith("#"):
                val = line.split("=", 1)[1].strip()
                if val:
                    return val
    print("ERROR: No OpenRouter API key found. Set OPENROUTER_API_KEY or pass --openrouter-api-key.",
          file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Simulate realistic user sessions using Claude via OpenRouter."
    )
    parser.add_argument(
        "--api-url", default="http://159.223.8.113",
        help="Deployed Reflexa API URL (default: %(default)s)",
    )
    parser.add_argument(
        "--openrouter-api-key", default=None,
        help="OpenRouter API key (default: from OPENROUTER_API_KEY env or .env)",
    )
    parser.add_argument(
        "--sessions", type=int, default=20,
        help="Number of sessions to simulate (default: %(default)s, max 20)",
    )
    parser.add_argument(
        "--turns-per-session", type=int, default=10,
        help="Turns per session (default: %(default)s)",
    )
    parser.add_argument(
        "--delay", type=float, default=2.0,
        help="Seconds to wait between turns (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print personas and sample prompts without making API calls",
    )
    args = parser.parse_args()

    if args.sessions > len(PERSONAS):
        parser.error(f"Max {len(PERSONAS)} sessions (number of defined personas)")

    key = _resolve_openrouter_key(args.openrouter_api_key) if not args.dry_run else "dry-run"

    asyncio.run(_run(
        api_url=args.api_url,
        openrouter_key=key,
        n_sessions=args.sessions,
        turns_per_session=args.turns_per_session,
        delay=args.delay,
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    main()

from reflexa.config import settings
from reflexa.db.engine import get_db  # re-export for routers
from reflexa.llm.client import build_llm_client, build_review_client

# Module-level singletons so the same clients are reused across requests
_llm_client = build_llm_client(settings)
_review_client = build_review_client(settings)


def get_llm_client():
    return _llm_client


def get_review_client():
    return _review_client

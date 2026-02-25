from reflexa.config import settings
from reflexa.db.engine import get_db  # re-export for routers
from reflexa.llm.client import build_llm_client

# Module-level singleton so the same client is reused across requests
_llm_client = build_llm_client(settings)


def get_llm_client():
    return _llm_client

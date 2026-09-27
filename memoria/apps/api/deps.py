from functools import lru_cache

from apps.api.settings import Settings, get_settings


@lru_cache
def get_qdrant_store():
    from apps.api.services.qdrant_store import QdrantStore

    return QdrantStore(get_settings())


@lru_cache
def get_embeddings():
    from apps.api.services.embeddings import EmbeddingService

    return EmbeddingService(get_settings())


@lru_cache
def get_lyzr_client():
    from apps.api.services.lyzr_client import LyzrClient

    return LyzrClient(get_settings())


@lru_cache
def get_pipeline():
    from apps.api.services.pipeline import Pipeline

    settings = get_settings()
    return Pipeline(
        settings=settings,
        store=get_qdrant_store(),
        embeddings=get_embeddings(),
        lyzr=get_lyzr_client(),
    )


def reset_caches() -> None:
    get_qdrant_store.cache_clear()
    get_embeddings.cache_clear()
    get_lyzr_client.cache_clear()
    get_pipeline.cache_clear()
    get_settings.cache_clear()

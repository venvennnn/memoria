import hashlib
import math

from openai import OpenAI

from apps.api.settings import Settings


class EmbeddingService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: OpenAI | None = None
        if settings.openai_api_key:
            self._client = OpenAI(api_key=settings.openai_api_key)

    def embed(self, text: str) -> list[float]:
        text = (text or "").strip()
        if not text:
            return [0.0] * self.settings.embedding_dim

        if self.settings.embedding_provider == "openai" and self._client:
            resp = self._client.embeddings.create(
                model=self.settings.embedding_model,
                input=text,
            )
            return list(resp.data[0].embedding)

        return self._deterministic_embed(text)

    def _deterministic_embed(self, text: str) -> list[float]:
        """Fallback when OpenAI is unavailable (dev/tests)."""
        dim = self.settings.embedding_dim
        vec = [0.0] * dim
        for i, token in enumerate(text.lower().split()):
            h = hashlib.sha256(f"{token}:{i}".encode()).digest()
            for j in range(min(8, dim)):
                idx = (j + i * 7) % dim
                vec[idx] += (h[j] / 255.0) - 0.5
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

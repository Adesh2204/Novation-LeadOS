import hashlib
import math
import re


def local_embedding(text: str) -> list[float]:
    vector = [0.0] * 64
    for token in re.findall(r"[a-z]+", text.lower()):
        digest = hashlib.sha256(token.encode()).digest()
        vector[int.from_bytes(digest[:2]) % 64] += 1 if digest[2] % 2 else -1
    norm = math.sqrt(sum(v * v for v in vector)) or 1
    return [v / norm for v in vector]


class MockEmbeddingProvider:
    name = "mock_embeddings"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [local_embedding(t) for t in texts]

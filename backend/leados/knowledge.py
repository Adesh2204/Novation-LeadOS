import json
from uuid import NAMESPACE_URL, uuid5

import yaml

from leados.config import ROOT
from leados.providers.base.embeddings import EmbeddingProvider
from leados.schemas import SignalDefinition, VerticalDefinition
from leados.storage.base import StorageProvider
from leados.storage.records import Service, Signal, SystemConfig, Vertical


class Knowledge:
    def __init__(self):
        self.verticals = {
            v.id: v
            for p in sorted((ROOT / "knowledge/verticals").glob("*.yaml"))
            if (v := VerticalDefinition.model_validate(yaml.safe_load(p.read_text())))
        }
        self.signals = {
            s.signal_id: s
            for row in yaml.safe_load((ROOT / "knowledge/signals/catalog.yaml").read_text())
            if (s := SignalDefinition.model_validate(row))
        }
        self.scoring = json.loads((ROOT / "knowledge/scoring.json").read_text())
        for signal in self.signals.values():
            if not set(signal.vertical_ids).issubset(self.verticals):
                raise ValueError(f"Unknown vertical in {signal.signal_id}")
        if sum(self.scoring["components"].values()) != 100:
            raise ValueError("Scoring weights must sum to 100")

    def seed(self, db: StorageProvider):
        for vertical in self.verticals.values():
            if not db.get(Vertical, vertical.id):
                db.add(Vertical(id=vertical.id, version=vertical.version, definition=vertical.model_dump()))
        for signal in self.signals.values():
            if not db.first(Signal, code=signal.signal_id):
                db.add(
                    Signal(
                        id="sig_" + str(uuid5(NAMESPACE_URL, "leados:signal:" + signal.signal_id)),
                        code=signal.signal_id,
                        version=signal.version,
                        definition=signal.model_dump(),
                    )
                )
        db.flush()
        config = {
            "ACTIVE_VERTICALS": "ALL",
            "EMAIL_SEND_ENABLED": "FALSE",
            "MIN_HOT_SCORE": str(next(b["min"] for b in self.scoring["bands"] if b["name"] == "HOT")),
            "MIN_STRONG_SCORE": str(next(b["min"] for b in self.scoring["bands"] if b["name"] == "STRONG")),
            "DEFAULT_RECENCY_DAYS": "30",
            "KNOWLEDGE_VERSION": next(iter(self.verticals.values())).version,
            "SCORING_VERSION": self.scoring["version"],
        }
        for key, value in config.items():
            if not db.first(SystemConfig, key=key):
                db.add(
                    SystemConfig(
                        id="cfg_" + str(uuid5(NAMESPACE_URL, "leados:config:" + key)), key=key, value=value
                    )
                )
        db.flush()
        for vertical in self.verticals.values():
            for i, service in enumerate(vertical.services):
                sid = f"{vertical.id}:{i}"
                if not db.get(Service, sid):
                    db.add(Service(id=sid, vertical_id=vertical.id, name=service))
        db.flush()

    async def retrieve_services(
        self,
        vertical_id: str,
        query: str,
        provider: EmbeddingProvider,
        preferred_services: list[str] | None = None,
    ) -> list[str]:
        # Small local RAG: restrict to the routed vertical, then rank its vetted services.
        # A live semantic embedding provider can replace the hashing adapter without domain changes.
        services = self.verticals[vertical_id].services
        vectors = await provider.embed([query, *services])
        preferred = preferred_services[0] if preferred_services else None
        ranked = sorted(
            zip(services, vectors[1:], strict=True),
            key=lambda pair: (
                (2 if pair[0] == preferred else 0)
                + sum(a * b for a, b in zip(vectors[0], pair[1], strict=True))
            ),
            reverse=True,
        )
        return [service for service, _ in ranked[:3]]


knowledge = Knowledge()

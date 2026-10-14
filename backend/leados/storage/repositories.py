"""Repository interfaces use domain records, never Sheet ranges or SQL queries."""

from leados.storage.base import StorageProvider
from leados.storage.records import (
    Company,
    FeedbackEvent,
    HumanReview,
    Opportunity,
    OpportunityEvidence,
    OutreachDraft,
    Record,
    Signal,
)


class Repository[T: Record]:
    model: type[T]

    def __init__(self, storage: StorageProvider):
        self.storage = storage

    def create(self, record: T):
        return self.storage.add(record)

    def update(self, oid: str, data: dict):
        return self.storage.update(self.model, oid, data)

    def get(self, oid: str):
        return self.storage.get(self.model, oid)

    def list(self, **filters):
        return self.storage.list(self.model, **filters)

    def find(self, **filters):
        return self.storage.first(self.model, **filters)


class CompanyRepository(Repository[Company]):
    model = Company

    def find_by_domain(self, domain: str, country: str):
        return self.find(domain=domain, country=country)

    def find_by_name(self, name: str, country: str):
        return self.find(canonical_name=name, country=country)


class SignalRepository(Repository[Signal]):
    model = Signal


class OpportunityRepository(Repository[Opportunity]):
    model = Opportunity


class EvidenceRepository(Repository[OpportunityEvidence]):
    model = OpportunityEvidence


class ReviewRepository(Repository[HumanReview]):
    model = HumanReview


class FeedbackRepository(Repository[FeedbackEvent]):
    model = FeedbackEvent


class OutreachRepository(Repository[OutreachDraft]):
    model = OutreachDraft

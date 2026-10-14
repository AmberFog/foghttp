from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class JsonPayload:
    created_at: datetime
    identifier: UUID

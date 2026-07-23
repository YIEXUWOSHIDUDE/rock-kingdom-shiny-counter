from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class HistoryEvent:
    type: str
    source: str
    before: int
    after: int
    at: str = field(default_factory=utc_now)
    id: str = field(default_factory=lambda: str(uuid4()))
    score: float | None = None


@dataclass(slots=True)
class PityRound:
    attempts: int
    pity_limit: int
    reached_pity: bool
    source: str
    at: str = field(default_factory=utc_now)
    id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError("round attempts must be positive")
        if self.pity_limit < 1:
            raise ValueError("round pity_limit must be positive")


@dataclass(slots=True)
class CounterState:
    target_name: str = "异色宠物"
    pity_limit: int = 80
    count: int = 0
    pity_reached: bool = False
    history: list[HistoryEvent] = field(default_factory=list)
    rounds: list[PityRound] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.pity_limit < 1:
            raise ValueError("pity_limit must be positive")
        if self.count < 0:
            raise ValueError("count cannot be negative")
        self.pity_reached = self.pity_reached or self.count >= self.pity_limit

    @property
    def remaining(self) -> int:
        return max(0, self.pity_limit - self.count)

    def increment(self, *, source: str, score: float | None = None) -> bool:
        before = self.count
        self.count += 1
        self.history.append(
            HistoryEvent(
                type="increment",
                source=source,
                before=before,
                after=self.count,
                score=score,
            )
        )
        reached_now = not self.pity_reached and self.count >= self.pity_limit
        if reached_now:
            self.pity_reached = True
            self.history.append(
                HistoryEvent(
                    type="pity_reached",
                    source="system",
                    before=self.count,
                    after=self.count,
                )
            )
        return reached_now

    def undo(self) -> bool:
        if self.count == 0:
            return False
        before = self.count
        self.count -= 1
        self.pity_reached = self.count >= self.pity_limit
        self.history.append(
            HistoryEvent(
                type="undo",
                source="manual",
                before=before,
                after=self.count,
            )
        )
        return True

    def reset(self, *, source: str = "manual") -> PityRound | None:
        before = self.count
        completed = None
        if before > 0:
            completed = PityRound(
                attempts=before,
                pity_limit=self.pity_limit,
                reached_pity=before >= self.pity_limit,
                source=source,
            )
            self.rounds.append(completed)
        self.count = 0
        self.pity_reached = False
        self.history.append(
            HistoryEvent(
                type="reset",
                source=source,
                before=before,
                after=0,
            )
        )
        return completed

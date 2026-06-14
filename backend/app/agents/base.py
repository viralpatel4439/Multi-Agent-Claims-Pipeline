import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AgentResult:
    success: bool
    data: Optional[dict]
    error: Optional[str]
    agent_name: str
    processing_time_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "agent_name": self.agent_name,
            "processing_time_ms": self.processing_time_ms,
        }


class AgentTimer:
    def __init__(self):
        self._start = None

    def start(self):
        self._start = time.monotonic()

    def elapsed_ms(self) -> int:
        if self._start is None:
            return 0
        return int((time.monotonic() - self._start) * 1000)

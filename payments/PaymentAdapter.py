from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MiddlewareSpec:
    middleware_cls: type[Any]
    kwargs: dict[str, Any]


class PaymentAdapter(ABC):
    @abstractmethod
    def get_middleware_specs(self) -> list[MiddlewareSpec]:
        """Return middleware specs that caller can attach to app."""

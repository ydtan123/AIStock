"""StockSelector ABC + ScoredTicker + registry.

Concrete selectors (e.g. FinrlStockSelector) live in this module as well.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Type

from pipeline.base import StepContext


@dataclass
class ScoredTicker:
    ticker: str
    ml_score: float
    sector: str | None = None


class _Registry:
    def __init__(self, label: str):
        self._label = label
        self._items: dict[str, Type] = {}

    def register(self, cls: Type) -> Type:
        if not getattr(cls, "name", None):
            raise TypeError(f"{cls.__name__} missing required 'name' attribute")
        self._items[cls.name] = cls
        return cls

    def unregister(self, name: str) -> None:
        self._items.pop(name, None)

    def get(self, name: str) -> Type:
        if name not in self._items:
            raise KeyError(f"unknown {self._label}: {name!r}")
        return self._items[name]

    def __contains__(self, name: str) -> bool:
        return name in self._items

    def names(self) -> list[str]:
        return sorted(self._items)


SELECTOR_REGISTRY = _Registry("selector")


class StockSelector(ABC):
    name: str = ""

    def __init__(self):
        if not self.name:
            raise TypeError(
                f"{type(self).__name__} must define a non-empty `name` class attribute"
            )

    @abstractmethod
    def select(self, ctx: StepContext) -> list[ScoredTicker]: ...

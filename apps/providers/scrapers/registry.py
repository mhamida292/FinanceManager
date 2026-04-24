from typing import Type

from .base import PriceScraper

_REGISTRY: dict[str, Type[PriceScraper]] = {}


def register(cls: Type[PriceScraper]) -> Type[PriceScraper]:
    _REGISTRY[cls.name] = cls
    return cls


def get(name: str = "css") -> PriceScraper:
    try:
        return _REGISTRY[name]()
    except KeyError as exc:
        raise ValueError(f"Unknown scraper: {name!r}. Registered: {sorted(_REGISTRY)}") from exc

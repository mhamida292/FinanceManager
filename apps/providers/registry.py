from typing import Type

from .base import FinancialProvider

_REGISTRY: dict[str, Type[FinancialProvider]] = {}


def register(provider_cls: Type[FinancialProvider]) -> Type[FinancialProvider]:
    """Class decorator / function that adds a provider to the registry by name."""
    _REGISTRY[provider_cls.name] = provider_cls
    return provider_cls


def get(name: str) -> FinancialProvider:
    """Return a fresh instance of the named provider."""
    try:
        cls = _REGISTRY[name]
    except KeyError as exc:
        raise ValueError(f"Unknown provider: {name!r}. Registered: {sorted(_REGISTRY)}") from exc
    return cls()

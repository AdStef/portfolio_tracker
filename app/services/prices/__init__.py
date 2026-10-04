"""Price-provider registry. Concrete online providers are added later; see base.PriceProvider."""

from .base import PricePoint, PriceProvider


class ManualProvider(PriceProvider):
    key = "manual"
    label = "Manual entry"
    fetchable = False
    needs_symbol = False


class BondFormulaProvider(PriceProvider):
    key = "bond_formula"
    label = "Polish treasury bond formula"
    fetchable = False
    needs_symbol = False


PROVIDERS: dict[str, PriceProvider] = {}


def register(provider: PriceProvider) -> None:
    PROVIDERS[provider.key] = provider


def get(key: str) -> PriceProvider | None:
    return PROVIDERS.get(key)


register(ManualProvider())
register(BondFormulaProvider())

__all__ = ["PricePoint", "PriceProvider", "PROVIDERS", "register", "get"]

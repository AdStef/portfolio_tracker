from dataclasses import dataclass
from datetime import date


@dataclass
class PricePoint:
    date: str  # YYYY-MM-DD
    close: float


class PriceProvider:
    """Link between an instrument and where its prices come from.

    To add a source (Yahoo, Stooq, a PPK fund page, ...): subclass, set ``key``/``label``,
    implement ``fetch`` and register it in ``app/services/prices/__init__.py``. The instrument then
    selects it via ``price_source`` and passes provider-specific data in ``source_symbol``/``source_config``.
    """

    key: str = ""
    label: str = ""
    fetchable: bool = True  # False = nothing to download (manual entry, formula)
    needs_symbol: bool = True

    def fetch(self, instrument: dict, since: date | None, until: date) -> list[PricePoint]:
        raise NotImplementedError

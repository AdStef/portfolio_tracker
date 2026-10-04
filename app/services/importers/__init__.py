"""CSV import profiles. Add broker formats by subclassing base.Importer and registering them here."""

from .base import Importer, ParsedRow
from .native import NativeImporter

IMPORTERS: dict[str, Importer] = {i.key: i for i in (NativeImporter(),)}

__all__ = ["IMPORTERS", "Importer", "ParsedRow"]

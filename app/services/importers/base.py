import csv
import io
from dataclasses import dataclass, field


@dataclass
class ParsedRow:
    line: int
    data: dict = field(default_factory=dict)  # keys understood by transactions.normalize()
    error: str | None = None


class Importer:
    """A CSV dialect. Broker exports (XTB, mBank, ...) get their own subclass that maps the broker's
    columns/operation names onto the keys accepted by ``transactions.normalize``.

    ``single_account``: the file belongs to one account picked in the UI (typical for broker exports).
    """

    key = ""
    label = ""
    single_account = False
    description = ""

    def parse(self, text: str) -> list[ParsedRow]:
        raise NotImplementedError


def read_csv(text: str) -> tuple[list[str], list[tuple[int, dict]]]:
    text = text.lstrip("﻿")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = [h.strip().lower() for h in reader.fieldnames or []]
    rows = []
    for row in reader:
        clean = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items() if k is not None}
        if any(clean.values()):
            rows.append((reader.line_num, clean))
    return headers, rows

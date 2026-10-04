from .base import Importer, ParsedRow, read_csv

COLUMNS = ["date", "person", "account", "type", "symbol", "instrument_name", "instrument_currency", "asset_class",
           "quantity", "price", "fee", "tax", "amount", "cash_currency", "fx_rate", "amount_pln",
           "counter_amount", "counter_currency", "note"]
REQUIRED = {"date", "type"}


class NativeImporter(Importer):
    key = "native"
    label = "Portfolio Tracker CSV"
    description = ("One row per transaction. Required columns: date, type, and account (unless an account is "
                   "selected). Decimal comma or dot, ',' or ';' separated.")

    def parse(self, text: str) -> list[ParsedRow]:
        headers, rows = read_csv(text)
        missing = REQUIRED - set(headers)
        if missing:
            return [ParsedRow(1, error=f"missing columns: {', '.join(sorted(missing))}")]
        return [ParsedRow(line, {k: v for k, v in row.items() if k in COLUMNS and v != ""}) for line, row in rows]


TEMPLATE = ",".join(COLUMNS) + "\n" + "\n".join([
    "2024-01-10,Adam,XTB PLN,DEPOSIT,,,,,,,,,1000,PLN,,,,,",
    "2024-01-11,Adam,XTB PLN,BUY,WSE:XTB,XTB SA,PLN,STOCK_PL,4,28.34,0,,,PLN,,,,,",
    "2024-01-12,Adam,XTB EUR,FX_EXCHANGE,,,,,,,,,997.94,PLN,,,229.00,EUR,",
    "2024-05-10,Adam,XTB PLN,DIVIDEND,WSE:XTB,,,,,,,2.50,13.00,PLN,,,,,net of tax",
]) + "\n"

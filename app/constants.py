"""Enumerations shared by the backend, templates and importers."""

ACCOUNT_KINDS = ["REGULAR", "BONDS", "IKE", "IKZE", "PPK"]
RETIREMENT_KINDS = {"IKE", "IKZE", "PPK"}

ASSET_CLASSES = [
    "STOCK_PL",
    "STOCK_INTL",
    "ETF_EQUITY",
    "ETF_BOND",
    "BOND_GOV_PL",
    "FUND",
    "CRYPTO",
    "COMMODITY",
    "FX",
    "OTHER",
]

TXN_TYPES = [
    "DEPOSIT",
    "WITHDRAWAL",
    "BUY",
    "SELL",
    "DIVIDEND",
    "INTEREST",
    "FEE",
    "TAX",
    "FX_EXCHANGE",
    "TRANSFER_IN",
    "TRANSFER_OUT",
    "EMPLOYER_CONTRIBUTION",
    "STATE_CONTRIBUTION",
]
TRADE_TYPES = {"BUY", "SELL"}
# Money entering/leaving an account from outside. Used for "invested" and XIRR cash flows.
EXTERNAL_FLOW_TYPES = {
    "DEPOSIT",
    "WITHDRAWAL",
    "TRANSFER_IN",
    "TRANSFER_OUT",
    "EMPLOYER_CONTRIBUTION",
    "STATE_CONTRIBUTION",
}

BASE_CURRENCY = "PLN"
DISPLAY_CURRENCIES = ["PLN", "EUR", "USD"]
LANGUAGES = ["pl", "en"]

"""Net ("after liquidation") value per account kind, under Polish rules as agreed for this app."""

BELKA = 0.19  # capital gains tax
IKZE_EXIT_TAX = 0.10  # flat tax on the whole IKZE value
PPK_EMPLOYER_LOSS = 0.30  # share of employer contributions that goes to ZUS on early withdrawal
# On early PPK withdrawal state contributions (welcome + annual bonus) are returned to the state too.
# The agreed rule only deducts the 30% employer share, so this is 0; set to 1.0 to also deduct them.
PPK_STATE_LOSS = 0.0


def net_value(kind: str, *, gross: float, liquidation_fees: float, positions_value: float, open_cost: float,
              own_contrib: float, employer_contrib: float, state_contrib: float) -> tuple[float, float]:
    """Returns (net value, tax/penalty deducted). All amounts in PLN.

    own_contrib is the account's net external money (deposits - withdrawals +/- transfers),
    employer/state contributions are only non-zero for PPK.
    """
    after_fees = gross - liquidation_fees
    if kind == "IKZE":
        tax = after_fees * IKZE_EXIT_TAX
    elif kind == "IKE":
        tax = BELKA * max(after_fees - own_contrib, 0.0)
    elif kind == "PPK":
        contributions = own_contrib + employer_contrib + state_contrib
        tax = (
            BELKA * max(after_fees - contributions, 0.0)
            + PPK_EMPLOYER_LOSS * employer_contrib
            + PPK_STATE_LOSS * state_contrib
        )
    else:  # REGULAR, BONDS: dividends/realised gains were taxed already, only open positions remain
        tax = BELKA * max(positions_value - liquidation_fees - open_cost, 0.0)
    return after_fees - tax, tax

from datetime import date


def xirr(flows: list[tuple[date, float]]) -> float | None:
    """Annualised internal rate of return. Flows are (date, amount) from the investor's view:
    money put in is negative, money taken out (incl. the final value) is positive."""
    flows = [(d, a) for d, a in flows if abs(a) > 1e-9]
    if len(flows) < 2 or not any(a < 0 for _, a in flows) or not any(a > 0 for _, a in flows):
        return None
    t0 = min(d for d, _ in flows)
    years = [((d - t0).days / 365.0, a) for d, a in flows]
    if max(t for t, _ in years) < 1e-9:
        return None

    def npv(rate):
        return sum(a / (1 + rate) ** t for t, a in years)

    # Bisection on (-99.99%, 1000%]: robust and plenty fast for a few thousand flows.
    lo, hi = -0.9999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-7 or hi - lo < 1e-10:
            break
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2

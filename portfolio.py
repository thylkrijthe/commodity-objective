"""Fixed holdings and their values at observed prices."""

import pandas as pd
import numpy as np

from markets import CommodityHolding, MARKETS

BASIS = ("Commodity quantity", "Currency amount", "ETF shares")


def resolve_amount(bars, holding):
    prices = bars.loc[bars.index.date >= holding.start_date]
    if prices.empty:
        raise ValueError("No prices exist on or after the holding start date.")
    if holding.basis == "Euro amount":
        if prices["Close"].iloc[0] <= 0:
            raise ValueError("A starting currency amount requires a positive reference price.")
        return holding.quantity / prices["Close"].iloc[0], prices.index[0], 1.
    return holding.amount, prices.index[0], prices["share_multiplier"].iloc[0]


def values(bars, amount, baseline, starting_multiplier, shares=False):
    selected = bars.loc[bars.index >= baseline].copy()
    factor = selected["share_multiplier"] / starting_multiplier if shares else 1.
    selected["holding_quantity"] = amount * factor
    selected["value"] = selected["Close"] * selected["holding_quantity"]
    return selected


def combined(series):
    """Require all holdings to have a quote for each total observation."""
    if not series:
        raise ValueError("Add at least one holding.")
    frame = pd.concat(series, axis=1, join="inner").dropna()
    if frame.empty:
        raise ValueError("These holdings have no common observed valuation dates.")
    frame["Total"] = frame.sum(axis=1)
    return frame


def make_lot(holding, currency, amount, baseline, starting_multiplier, label):
    return {
        "label": label, "market": holding.market, "basis": holding.basis,
        "quantity": holding.quantity, "unit": holding.unit,
        "start_date": holding.start_date.isoformat(), "input_currency": currency,
        "amount": float(amount), "baseline": baseline.isoformat(),
        "starting_multiplier": float(starting_multiplier), "kg_conversion": holding.kg_conversion,
    }


def validate_lots(lots):
    if not isinstance(lots, list) or not 1 <= len(lots) <= 100:
        raise ValueError("Portfolio files must contain 1 to 100 holdings.")
    checked = []
    for lot in lots:
        if lot["market"] not in MARKETS or lot["basis"] not in ("Commodity quantity", "Euro amount", "ETF shares"):
            raise ValueError("Unrecognised commodity or holding type in portfolio file.")
        for key in ("quantity", "amount", "starting_multiplier"):
            if not np.isfinite(lot[key]) or lot[key] <= 0:
                raise ValueError("Portfolio quantities must be finite and positive.")
        if pd.Timestamp(lot["baseline"]).tzinfo is None:
            raise ValueError("Portfolio baseline timestamps must include their timezone.")
        checked.append(lot)
    return checked

"""Commodity reference units and historical data."""

from dataclasses import dataclass
from datetime import date

import numpy as np

TROY_OUNCES_PER_KG = 1000 / 31.1034768

START = date(1999, 1, 4)


@dataclass(frozen=True)
class Market:
    ticker: str
    unit: str
    factor: float
    units: dict
    etf: str


MARKETS = {
    "Silver": Market("SI=F", "kg", TROY_OUNCES_PER_KG, {"troy oz": 1 / TROY_OUNCES_PER_KG, "kg": 1}, "SLV"),
    "Gold": Market("GC=F", "kg", TROY_OUNCES_PER_KG, {"troy oz": 1 / TROY_OUNCES_PER_KG, "kg": 1}, "GLD"),
    "Platinum": Market("PL=F", "kg", TROY_OUNCES_PER_KG, {"troy oz": 1 / TROY_OUNCES_PER_KG, "kg": 1}, "PPLT"),
    "Copper": Market("HG=F", "kg", 1 / 0.45359237, {"lb": 0.45359237, "kg": 1, "tonnes": 1000}, "CPER"),
    "WTI crude oil": Market("CL=F", "barrel", 1, {"barrels": 1, "kg": None}, "USO"),
    "Natural gas": Market("NG=F", "MMBtu", 1, {"MMBtu": 1, "kg": None}, "UNG"),
    "Corn": Market("ZC=F", "tonne", 1000 / 25.40117272 / 100, {"bushels": 25.40117272 / 1000, "kg": .001, "tonnes": 1}, "CORN"),
    "Wheat": Market("ZW=F", "tonne", 1000 / 27.2155422 / 100, {"bushels": 27.2155422 / 1000, "kg": .001, "tonnes": 1}, "WEAT"),
}


@dataclass(frozen=True)
class CommodityHolding:
    quantity: float
    unit: str
    start_date: date
    market: str
    basis: str = "Commodity quantity"
    kg_conversion: float | None = None

    def __post_init__(self):
        if not np.isfinite(self.quantity) or self.quantity <= 0:
            raise ValueError("Enter a positive quantity or euro amount.")
        if self.basis not in ("Commodity quantity", "Euro amount", "ETF shares"):
            raise ValueError("Choose a supported holding type.")
        if self.basis == "Commodity quantity" and self.unit not in MARKETS[self.market].units:
            raise ValueError("Choose a supported commodity unit.")
        if self.basis == "Commodity quantity" and MARKETS[self.market].units[self.unit] is None:
            if self.kg_conversion is None or not np.isfinite(self.kg_conversion) or self.kg_conversion <= 0:
                raise ValueError("Enter the density or energy content needed to convert kilograms.")

    @property
    def amount(self):
        if self.basis == "ETF shares":
            return self.quantity
        if self.basis == "Euro amount":
            raise ValueError("Euro amounts require the starting reference price.")
        factor = MARKETS[self.market].units[self.unit]
        if factor is None:
            if self.market == "WTI crude oil":
                factor = 1 / (158.987294928 * self.kg_conversion)
            else:
                factor = self.kg_conversion
        return self.quantity * factor


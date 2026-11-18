"""Observed commodity prices and explicitly dated currency conversions."""

from datetime import datetime, UTC, timedelta
from zoneinfo import ZoneInfo
from urllib.request import urlopen
from urllib.parse import urlencode
import json
from functools import lru_cache
from urllib.error import HTTPError, URLError
import time

import numpy as np
import pandas as pd
import yfinance as yf

from markets import MARKETS

CURRENCIES = ("EUR", "USD", "KZT", "GBP", "CHF", "JPY", "CAD", "AUD", "NZD", "CNY", "HKD", "SGD", "INR")
# Yahoo instruments quoted as USD per foreign unit need inversion.
FX_TICKERS = {
    "EUR": ("EURUSD=X", True), "GBP": ("GBPUSD=X", True),
    "AUD": ("AUDUSD=X", True), "NZD": ("NZDUSD=X", True),
    "CHF": ("CHF=X", False), "JPY": ("JPY=X", False),
    "CAD": ("CAD=X", False), "CNY": ("CNY=X", False),
    "HKD": ("HKD=X", False), "SGD": ("SGD=X", False),
    "INR": ("INR=X", False),
}
INTERVALS = {"Daily": ("1d", None), "Hourly": ("1h", "1mo"),
             "5 minutes": ("5m", "5d"), "1 minute": ("1m", "5d")}


@lru_cache(maxsize=256)
def _reference_chunk(currency, start, end, provider, cache_window):
    query = urlencode({"base": "USD", "quotes": currency, "from": start,
                       "to": end, "providers": provider})
    for attempt in range(3):
        try:
            with urlopen(f"https://api.frankfurter.dev/v2/rates?{query}", timeout=20) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code not in (429, 502, 503, 504) or attempt == 2:
                raise ValueError(f"The currency reference service is unavailable ({error.code}). Please retry later.") from error
            requested = error.headers.get("Retry-After", "")
            delay = float(requested) if requested.isdigit() else 5 * (attempt + 1)
            if delay > 60:
                raise ValueError("The currency provider requests a longer wait. Please retry later.") from error
            time.sleep(delay)
        except (URLError, TimeoutError) as error:
            if attempt == 2:
                raise ValueError("The currency reference service did not respond. Please retry later.") from error
            time.sleep(2 * (attempt + 1))


def reference_rates(currency, start):
    """Daily central-bank references, target currency per one USD, via Frankfurter."""
    if currency not in CURRENCIES:
        raise ValueError("Choose a supported currency.")
    provider = "NBK" if currency == "KZT" else "ECB"
    beginning = pd.Timestamp(start).date()
    today = datetime.now(UTC).date()
    rows = []
    # Daily provider attribution requires bounded requests on this API.
    while beginning <= today:
        ending = min(beginning + timedelta(days=1460), today)
        part = _reference_chunk(currency, beginning.isoformat(), ending.isoformat(),
                                provider, int(time.time() // 21600))
        if not isinstance(part, list):
            raise ValueError("The FX service returned an invalid response.")
        rows.extend(part)
        beginning = ending + timedelta(days=1)
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"No {currency} reference rates were returned.")
    frame = pd.DataFrame(rows)
    frame["providers"] = provider
    frame["date"] = pd.to_datetime(frame["date"], utc=True)
    frame = frame.set_index("date").sort_index()
    frame.index = frame.index.as_unit("ns")
    frame = frame.loc[~frame.index.duplicated(keep="last")]
    frame["rate"] = pd.to_numeric(frame["rate"], errors="coerce")
    if not frame.index.is_unique or not np.isfinite(frame["rate"]).all() or (frame["rate"] <= 0).any():
        raise ValueError("Invalid currency reference rates were returned.")
    frame["provider"] = frame.get("providers", pd.Series([[]] * len(frame), index=frame.index)).apply(
        lambda providers: json.dumps(providers, ensure_ascii=False)
    )
    return frame[["rate", "provider"]]


def raw_prices(name, etf=False, interval="Daily"):
    spec = MARKETS[name]
    symbol = spec.etf if etf else spec.ticker
    code, period = INTERVALS[interval]
    options = {"start": "1999-01-04", "end": datetime.now(ZoneInfo("America/New_York")).date().isoformat()} if period is None else {"period": period}
    frame = yf.download(symbol, **options, interval=code, auto_adjust=False, actions=etf,
                        multi_level_index=False, ignore_tz=False, progress=False, threads=False, timeout=15)
    if frame is None or frame.empty or not {"Open", "Close"}.issubset(frame.columns):
        raise ValueError(f"No {interval.lower()} observations returned for {symbol}.")
    index = pd.DatetimeIndex(frame.index)
    # Daily dates identify sessions. Intraday timestamps must be timezone-aware.
    if interval == "Daily":
        index = pd.to_datetime(index.date, utc=True)
    elif index.tz is None:
        raise ValueError("The intraday feed did not identify the timestamp timezone.")
    else:
        index = index.tz_convert("UTC")
    frame.index = index.as_unit("ns")
    frame = frame.sort_index()
    if not frame.index.is_unique:
        raise ValueError("The feed returned duplicate observation times.")
    frame = frame.loc[np.isfinite(frame[["Open", "Close"]]).all(axis=1)].copy()
    if frame.empty:
        raise ValueError("No complete price observations were returned.")
    frame["share_multiplier"] = 1.
    if etf and interval == "Daily":
        splits = frame.get("Stock Splits", pd.Series(0., index=frame.index)).fillna(0).replace(0, 1)
        future = splits.iloc[::-1].cumprod().iloc[::-1] / splits
        frame[["Open", "Close"]] = frame[["Open", "Close"]].mul(future, axis=0)
        frame["share_multiplier"] = splits.cumprod()
    factor = 1 if etf else spec.factor
    frame[["Open", "Close"]] *= factor
    frame.attrs.update(symbol=symbol, interval=interval, retrieved_utc=datetime.now(UTC).isoformat(),
                       source="Yahoo Finance", unit="share" if etf else spec.unit)
    return frame[["Open", "Close", "share_multiplier"]]


def convert_prices(raw, currency, rates=None, intraday_fx=None):
    """Convert without matching a price observation to a later FX observation."""
    result = raw.copy()
    result.index = result.index.as_unit("ns")
    if currency == "USD":
        result["fx_rate"] = 1.
        result["fx_time"] = result.index
        result["fx_provider"] = "USD quote currency"
        result.attrs.update(raw.attrs, currency=currency, fx_method="USD quote; no conversion")
        return result
    if intraday_fx is not None:
        fx = intraday_fx.dropna().sort_index().copy()
        fx.index = fx.index.as_unit("ns")
        fx = fx.loc[np.isfinite(fx) & fx.gt(0)]
        aligned = pd.merge_asof(
            result, fx.rename("fx_rate").to_frame().assign(fx_time=fx.index),
            left_index=True, right_index=True, direction="backward", tolerance=pd.Timedelta(hours=1),
        )
        aligned["fx_provider"] = "Yahoo Finance"
        method = "Timestamp-matched intraday FX; quotes may be delayed"
        open_rate = aligned["fx_rate"]
    else:
        if rates is None or rates.empty:
            raise ValueError(f"No reference FX data available for {currency}.")
        # Intraday references are conservatively available from the following UTC day.
        fx = rates.rename(columns={"rate": "fx_rate", "provider": "fx_provider"}).copy()
        fx.index = fx.index.as_unit("ns")
        fx["fx_time"] = fx.index
        intraday = raw.attrs.get("interval", "Daily") != "Daily"
        fx.index = fx.index + (pd.Timedelta(days=1) if intraday else pd.Timedelta(0))
        aligned = pd.merge_asof(result, fx, left_index=True, right_index=True,
                                direction="backward", tolerance=pd.Timedelta(days=7))
        if intraday:
            open_rate = aligned["fx_rate"]
        else:
            prior = rates["rate"].reindex(result.index - pd.Timedelta(days=1), method="ffill",
                                          tolerance=pd.Timedelta(days=7))
            open_rate = pd.Series(prior.to_numpy(), index=result.index)
        method = "Daily reference FX; same-date close and preceding-date open" if not intraday else "Prior-day reference FX; not an intraday currency quote"
    aligned["Open"] *= open_rate
    aligned["Close"] *= aligned["fx_rate"]
    aligned = aligned.dropna(subset=["Open", "Close", "fx_rate"])
    if aligned.empty:
        raise ValueError("No observed prices had a currency rate within the permitted age.")
    if aligned.index[-1] != raw.index[-1]:
        raise ValueError("The latest commodity observation has no sufficiently recent currency rate.")
    aligned.attrs.update(raw.attrs, currency=currency, fx_method=method)
    return aligned


def observed_fx(currency, interval):
    if currency not in FX_TICKERS:
        raise ValueError(f"No configured intraday quote source for {currency}.")
    symbol, invert = FX_TICKERS[currency]
    code, period = INTERVALS[interval]
    raw = yf.download(symbol, period=period, interval=code, auto_adjust=False,
                      multi_level_index=False, ignore_tz=False, progress=False, threads=False, timeout=15)
    if raw is None or raw.empty or "Close" not in raw:
        raise ValueError(f"No intraday observations for {symbol}.")
    fx = raw["Close"].dropna()
    if fx.index.tz is None:
        raise ValueError("The FX feed did not identify its timestamp timezone.")
    fx.index = fx.index.tz_convert("UTC")
    return 1 / fx if invert else fx


def quality(frame):
    latest = frame.index[-1]
    age = max(0, int((datetime.now(UTC) - latest).total_seconds() / 60))
    return {
        "symbol": frame.attrs["symbol"], "source": frame.attrs["source"],
        "resolution": frame.attrs["interval"], "latest_observation_utc": latest.isoformat(),
        "retrieved_utc": frame.attrs["retrieved_utc"], "age_minutes": age,
        "fx_method": frame.attrs["fx_method"], "fx_date_or_time": str(frame["fx_time"].iloc[-1]),
        "fx_provider": str(frame["fx_provider"].iloc[-1]), "currency": frame.attrs["currency"],
    }

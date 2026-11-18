# Commodity tracker

This edition adds currencies, interval charts, a moving ticker, multiple holdings and combined portfolio valuations. All price views identify the observed instrument, latest price date or bar time, retrieval time, currency method and FX date or time.

## Update your phone app

Copy the contents of this folder into your existing GitHub repository, keeping `app.py` at its root. Include `quotes.py`, `portfolio.py` and `charts.py`, along with the existing calculation modules and requirements. Commit and push. Streamlit rebuilds the same app link. Use Python 3.14.

To run locally from this folder:

```bash
~/python-envs/mude/bin/python -m pip install -r requirements.txt
~/python-envs/mude/bin/python -m streamlit run app.py
```

## Currencies and timing

The display currencies are USD, EUR, KZT, GBP, CHF, JPY, CAD, AUD, NZD, CNY, HKD, SGD and INR. Futures and US-listed funds are quoted in USD. USD values require no currency conversion.

Historical conversions use Frankfurter v2's provider-specific references from the European Central Bank (ECB), or the National Bank of Kazakhstan (NBK) for KZT. The source detail panel reports that provider. Same-date reference rates are used for daily close valuation and prior-date references for simulated opening fills. Their dates do not identify the exact publication time or an executable conversion price.

The intraday screen offers timestamp-matched Yahoo Finance FX quotes for configured major currencies. Each commodity observation uses an FX observation at or before its bar time, with a maximum one-hour match tolerance. If the newest commodity bar cannot be matched, the app reports an error rather than silently presenting an older matched bar as latest.

KZT uses daily reference rates. For intraday reference conversions, a reference dated January 5 is used from January 6 UTC onward. This conservative lag avoids assuming an exact publication time. KZT intraday values combine an intraday commodity observation with a dated reference conversion and are labelled accordingly. Daily reference gaps of up to seven days can use the last prior observation; its actual date remains visible. Older gaps are excluded. The app reports when the latest commodity observation cannot be converted.

## Charts and ticker

Choose daily, hourly, five-minute or one-minute observations. Daily requests cover history from 1999 where quotes are available. Hourly requests cover a month; finer intervals request five days. Provider coverage can be shorter and can vary by instrument. Seconds data is unavailable through this feed.

The newest intraday bar can be incomplete and the feed may be delayed. Polling every minute checks for updates but cannot guarantee new observations. The chart includes actual returned observations without interpolating additional points. Its vertical range follows the selected visible window so smaller movements can be inspected. A tight vertical scale magnifies small changes visually; read the numbers on the axis. The chart loads Plotly's official JavaScript bundle from its CDN.

The moving board shows completed daily futures reference closes for every configured commodity and the change from the preceding available daily close. It checks cached data every 15 minutes while the session is open. Each item shows its session date. The motion is a display effect. A failed source is labelled unavailable.

## Holdings and combined portfolio

Add any number of lots under My holdings, including multiple lots of the same commodity. Each entry can be commodity quantity, a starting currency amount, or ETF shares. A currency amount resolves into a fixed quantity at the first available close on or after its start date, denominated in the display currency selected at creation. Changing display currency subsequently keeps that quantity fixed.

Metals use kilograms or troy ounces. Copper also offers pounds and tonnes, grains offer kilograms, tonnes and bushels. Oil uses barrels; its kg conversion requires the supplied density. Gas uses MMBtu; its kg conversion requires supplied energy content.

ETF holdings use SLV, GLD, PPLT, CPER, USO, UNG, CORN or WEAT. Starting shares are adjusted for subsequent splits. Cash dividends are excluded. Commodity quantities are valued from futures references and can differ from actual physical resale prices.

The Portfolio screen totals selected lots in one display currency. The combined history includes only dates on which all included lots have an observation. Its starting date follows the latest holding start, and its latest common date can precede some individual latest quotes. This comparison does not model a deposit-adjusted investment return.

Holdings are kept in the current session. Download the portfolio JSON and restore it later. CSV exports include observed prices, source timing and currency information. Portfolio files contain your quantities and should be stored privately.

## Strategy lab

All strategy rules are user-selected examples. The fractional allocation engine is retained, including next-session opening execution, fees and walk-forward evaluation. It is a simplified continuous futures simulation. Futures contract rolls, margin requirements, whole contracts, storage, taxes, spread and separate slippage are omitted. It does not establish an investment advantage. Periods containing zero or negative reference prices cannot run through the positive-price allocation model. Price history retains those observations.

## Verification

```bash
~/python-envs/mude/bin/python -m unittest discover -s tests -v
```

The regression checks cover time-aligned FX, KZT reference availability, unit conversions, split accounting and combined histories with missing observations.

[Yahoo Finance data API documentation](https://ranaroussi.github.io/yfinance/reference/yfinance.functions.html) · [Frankfurter reference rates and provider coverage](https://frankfurter.dev/) · [National Bank of Kazakhstan rate metadata](https://nationalbank.kz/en/news/metadannye/7252)

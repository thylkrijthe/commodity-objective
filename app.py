"""Commodity valuation dashboard with traceable sources and date-aligned currency conversion."""

from dataclasses import asdict, replace
from datetime import date, datetime, UTC
from html import escape
import json

import pandas as pd
import streamlit as st

from backtest import Account
from analytics import summary
from charts import plot
from markets import MARKETS, START, CommodityHolding
from portfolio import resolve_amount, values, combined, make_lot, validate_lots
from quotes import CURRENCIES, FX_TICKERS, INTERVALS, raw_prices, reference_rates, observed_fx, convert_prices, quality
from research import fixed_run, walk_forward
from strategies import Parameters, STRATEGIES


@st.cache_data(ttl=900, max_entries=80, show_spinner=False)
def daily_raw(name, etf=False):
    return raw_prices(name, etf)


@st.cache_data(ttl=21600, max_entries=40, show_spinner=False)
def fx_reference(currency, start):
    return reference_rates(currency, start)


@st.cache_data(ttl=50, max_entries=60, show_spinner=False)
def recent_raw(name, etf, interval):
    return raw_prices(name, etf, interval)


@st.cache_data(ttl=50, max_entries=40, show_spinner=False)
def fx_recent(currency, interval):
    return observed_fx(currency, interval)


def quoted(name, currency, etf=False, interval="Daily", fx_mode="Daily reference"):
    raw = daily_raw(name, etf) if interval == "Daily" else recent_raw(name, etf, interval)
    if currency == "USD":
        return convert_prices(raw, currency)
    if interval != "Daily" and fx_mode == "Intraday FX":
        return convert_prices(raw, currency, intraday_fx=fx_recent(currency, interval))
    rates = fx_reference(currency, date(1998, 12, 20) if interval == "Daily" else (raw.index[0] - pd.Timedelta(days=8)).date())
    return convert_prices(raw, currency, rates=rates)


def money(value):
    return f"{currency} {value:,.2f}"


def source_panel(frame):
    info = quality(frame)
    st.caption(f"{info['symbol']} · {info['resolution']} observations · "
               f"Latest {info['latest_observation_utc']} · {info['age_minutes']:,} minutes old")
    st.caption(f"FX {info['fx_method']} · Reference/quote time {info['fx_date_or_time']}")
    if info["age_minutes"] > (7 * 1440 if info["resolution"] == "Daily" else 120):
        st.warning("These observations are old. Market closures or a delayed feed may explain the age.")
    with st.expander("Source and calculation details"):
        st.json(info)
        st.write("Daily dates identify trading sessions. Intraday times identify the start of each bar; the newest bar may still be forming.")
        st.write("Yahoo Finance is a delayed or indicative feed. Daily FX reference dates do not identify an executable rate or its exact publication time.")
        st.write("Commodity holdings use continuous futures references. Contract rolls, physical premiums, storage, tax and dealer spreads can change realised values.")


def csv_button(frame, name):
    export = frame.copy()
    for key, value in frame.attrs.items():
        export[f"metadata_{key}"] = str(value)
    st.download_button("Download observations and source details", export.to_csv(index_label="timestamp_utc"),
                       name, "text/csv", key=f"csv-{name}")


@st.fragment(run_every="15min")
def ticker_board():
    # Completed daily bars are identified honestly, independent of visual motion.
    cards = []
    for name, market in MARKETS.items():
        try:
            bars = quoted(name, currency)
            latest, previous = bars.Close.iloc[-1], bars.Close.iloc[-2]
            change = (latest / previous - 1) * 100 if previous > 0 else None
            suffix = f"{change:+.2f}%" if change is not None else "change unavailable"
            cards.append(f"<span><b>{escape(name)}</b> {currency} {latest:,.3f}/{market.unit}"
                         f" <i>{suffix}</i><small>{bars.index[-1]:%d %b %Y} · daily close</small></span>")
        except (ValueError, OSError, KeyError) as error:
            cards.append(f"<span><b>{escape(name)}</b><small>Quote unavailable</small></span>")
    content = "".join(cards)
    st.iframe("""<style>
body{margin:0;font:14px system-ui;background:#162a2b;color:#f4f6f3}
.wall{overflow:hidden;padding:14px 0}.strip{display:flex;width:max-content;animation:slide 65s linear infinite}
.strip span{padding:0 24px;border-right:1px solid #526460;white-space:nowrap}
small{display:block;color:#bdcac7;font-size:11px;margin-top:3px}i{font-style:normal;color:#d2c393}
.wall:hover .strip,.wall:focus-within .strip{animation-play-state:paused}
@keyframes slide{to{transform:translateX(-50%)}}
@media(prefers-reduced-motion:reduce){.strip{animation:none}.wall{overflow-x:auto}}
</style><div class="wall" tabindex="0" aria-label="Completed daily commodity closes"><div class="strip">"""
                    + content + '<div aria-hidden="true" style="display:flex">' + content + "</div></div></div>", height=77)
    st.caption("Ticker shows completed daily futures reference closes in the selected currency. It checks for updates every 15 minutes while open. Motion does not indicate live trading.")


def holding_editor():
    st.subheader("Value a holding")
    basis = st.radio("Input type", ["Commodity quantity", "Currency amount", "ETF shares"], horizontal=True)
    unit = currency if basis == "Currency amount" else "shares"
    conversion = None
    if basis == "Commodity quantity":
        unit = st.selectbox("Unit", list(market.units), format_func=lambda x: {
            "kg": "Kilograms (kg)", "troy oz": "Troy ounces", "lb": "Pounds (lb)",
            "MMBtu": "Million BTU (MMBtu)"}.get(x, x.capitalize()))
        if market.units[unit] is None:
            conversion = st.number_input(
                "Oil density (kg/litre)" if name == "WTI crude oil" else "Gas energy content (MMBtu/kg)",
                min_value=0., value=0., format="%.6f")
            st.caption("Enter the specification of your material to convert its weight.")
    if basis == "Currency amount":
        st.caption(f"Starting {currency} buys a hypothetical fixed quantity at the first available reference close. It excludes transaction, holding and storage costs.")
    if basis == "ETF shares":
        st.caption(f"Fund {market.etf}. Share splits are included and cash dividends excluded.")
    with st.form("value-holding"):
        quantity = st.number_input(f"Starting {currency}" if basis == "Currency amount" else "Quantity",
                                   min_value=0., max_value=1e12, value=0., step=1.)
        start = st.date_input("Held since", value=date(2018, 1, 1), min_value=START, max_value=date.today())
        label = st.text_input("Holding name", value=f"{name} holding")
        submitted = st.form_submit_button("Value holding and add to portfolio", type="primary")
    if submitted:
        try:
            internal_basis = "Euro amount" if basis == "Currency amount" else basis
            holding = CommodityHolding(quantity, unit, start, name, internal_basis, conversion)
            bars = quoted(name, currency, basis == "ETF shares")
            amount, baseline, multiplier = resolve_amount(bars, holding)
            lot = make_lot(holding, currency, amount, baseline, multiplier, label or f"{name} holding")
            st.session_state.lots.append(lot)
            st.session_state.latest_lot = lot
        except (ValueError, OSError) as error:
            st.error(str(error))
    lot = st.session_state.get("latest_lot")
    if lot is None:
        return
    try:
        bars = quoted(lot["market"], currency, lot["basis"] == "ETF shares")
        history = values(bars, lot["amount"], pd.Timestamp(lot["baseline"]), lot["starting_multiplier"],
                         lot["basis"] == "ETF shares")
        value = history.value
        st.metric(lot["label"], money(value.iloc[-1]),
                  f"{(value.iloc[-1] / value.iloc[0] - 1) * 100:+.2f}%" if value.iloc[0] > 0 else None)
        st.caption(f"Valuation begins {history.index[0]:%d %b %Y}; first available observations can follow your chosen start date.")
        plot({lot["label"]: value}, currency, "holding")
        source_panel(bars)
        csv_button(history, "holding.csv")
    except (ValueError, OSError) as error:
        st.error(str(error))


def portfolio_page():
    st.subheader("Combined portfolio")
    lots = st.session_state.lots
    upload = st.file_uploader("Restore an exported portfolio", type="json")
    if upload is not None and st.button("Restore holdings"):
        try:
            restored = validate_lots(json.load(upload))
            if any(lot["input_currency"] not in CURRENCIES for lot in restored):
                raise ValueError("Unrecognised input currency.")
            st.session_state.lots = lots = restored
        except (ValueError, KeyError, TypeError) as error:
            st.error(f"Could not restore this file: {error}")
    if not lots:
        st.info("Add holdings under My holdings. You can add multiple lots of the same commodity.")
        return
    labels = [f"{i + 1}. {lot['label']} · {lot['market']}" for i, lot in enumerate(lots)]
    chosen = st.multiselect("Include holdings", range(len(lots)), default=list(range(len(lots))),
                            format_func=lambda i: labels[i])
    st.download_button("Save portfolio for another session", json.dumps(lots, indent=2),
                       "my-commodity-portfolio.json", "application/json")
    remove = st.selectbox("Remove a holding", [None, *range(len(lots))],
                           format_func=lambda i: "Choose a holding" if i is None else labels[i])
    if st.button("Remove selected holding", disabled=remove is None):
        del st.session_state.lots[remove]
        st.rerun()
    if not chosen:
        return
    series, rows = {}, []
    try:
        for i in chosen:
            lot = lots[i]
            frame = quoted(lot["market"], currency, lot["basis"] == "ETF shares")
            history = values(frame, lot["amount"], pd.Timestamp(lot["baseline"]),
                             lot["starting_multiplier"], lot["basis"] == "ETF shares")
            series[labels[i]] = history.value
            rows.append({"Holding": labels[i], "Latest source session": str(history.index[-1].date()),
                         "FX reference date": str(history.fx_time.iloc[-1]), "Currency": currency,
                         "Latest individual value": history.value.iloc[-1]})
        total = combined(series)
        total.attrs.update(currency=currency, alignment="Common observed dates only",
                           holdings=json.dumps([lots[i] for i in chosen]),
                           source_details=pd.DataFrame(rows).to_json(orient="records"))
        st.metric("Combined reference value", money(total.Total.iloc[-1]),
                  f"{(total.Total.iloc[-1] / total.Total.iloc[0] - 1) * 100:+.2f}% over common period" if total.Total.iloc[0] > 0 else None)
        st.caption(f"Common observed period {total.index[0]:%d %b %Y} to {total.index[-1]:%d %b %Y}. "
                   "Only dates with observations for every included holding are totalled. The chart begins after every holding has started.")
        components_visible = st.checkbox("Show each holding", value=False)
        plot({column: total[column] for column in total.columns} if components_visible else {"Total": total.Total},
             currency, "portfolio")
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption("Individual latest quotes can be newer than the combined valuation date. Changing display currency preserves each lot's original quantity.")
        csv_button(total, "portfolio.csv")
    except (ValueError, OSError) as error:
        st.error(str(error))


def price_page():
    st.subheader("Observed market history")
    interval = st.selectbox("Observation interval", list(INTERVALS))
    st.caption("Second-by-second data is unavailable from the configured feed. Each chart point is an actual returned observation.")
    fx_mode = "Daily reference"
    if interval != "Daily" and currency != "USD":
        modes = ["Daily reference", "Intraday FX"] if currency in FX_TICKERS else ["Daily reference"]
        fx_mode = st.radio("Currency conversion", modes, horizontal=True,
                           index=1 if len(modes) > 1 else 0)
        if currency == "KZT":
            st.info("KZT uses dated daily reference rates. Intraday commodity changes are converted at a prior-day reference rate, so this is an indicative KZT value.")
    live = st.toggle("Check for updates every minute", value=False) if interval != "Daily" else False

    @st.fragment(run_every="60s" if live else None)
    def render():
        st.button("Refresh view")
        try:
            frame = quoted(name, currency, interval=interval, fx_mode=fx_mode)
            choices = {"Daily": ["All", "5 years", "1 year", "1 month", "1 week"],
                       "Hourly": ["All", "1 week", "1 day"],
                       "5 minutes": ["All", "1 day", "6 hours", "1 hour"],
                       "1 minute": ["All", "1 day", "6 hours", "1 hour"]}[interval]
            window = st.selectbox("Visible window", choices, key=f"window-{interval}")
            durations = {"5 years": "1826D", "1 year": "366D", "1 month": "31D",
                         "1 week": "7D", "1 day": "1D", "6 hours": "6h", "1 hour": "1h"}
            visible = frame if window == "All" else frame.loc[frame.index >= frame.index[-1] - pd.Timedelta(durations[window])]
            st.metric("Latest observed reference price", f"{money(frame.Close.iloc[-1])}/{market.unit}")
            plot({name: visible.Close}, f"{currency}/{market.unit}", "market-history", interval)
            st.caption("The vertical scale follows the visible observations. Small moves may look large after zooming; use the axis values to judge their size.")
            source_panel(frame)
            csv_button(frame, "prices.csv")
        except (ValueError, OSError) as error:
            st.error(str(error))
    render()


def strategy_page():
    st.subheader("Strategy lab")
    st.info("Simulation with user-selected example rules. Continuous futures are modelled as fractional holdings. Contract rolls, margin, storage, execution spreads and taxes are omitted. Results do not establish a trading advantage.")
    mode = st.selectbox("Mode", ["Single strategy", "Compare strategies", "Walk-forward"])
    strategy = st.selectbox("Strategy", STRATEGIES) if mode != "Compare strategies" else STRATEGIES[0]
    with st.form("backtest"):
        start = st.date_input("Backtest start", value=date(2018, 1, 1), min_value=START, max_value=date.today())
        capital = st.number_input(f"Starting capital ({currency})", min_value=1., value=10_000.)
        allocation = st.slider("Allocation (%)", 1, 100, 25)
        fee = st.number_input("Cost per traded notional (basis points)", min_value=0., max_value=9999., value=10.)
        slow = st.number_input("Lookback / slow average (sessions)", min_value=5, max_value=250, value=20)
        fast = st.number_input("Fast average (sessions)", min_value=1, max_value=249, value=10)
        entry = st.number_input("Mean reversion entry threshold (%)", min_value=0., max_value=99., value=2.)
        exit_threshold = st.number_input("Mean reversion exit threshold (%)", min_value=0., max_value=100., value=2.)
        train = st.number_input("Walk-forward training sessions", min_value=3, value=504)
        test = st.number_input("Walk-forward test sessions", min_value=1, value=126)
        run = st.form_submit_button("Run simulation", type="primary")
    identity = (name, currency, mode, strategy)
    if run:
        try:
            frame = quoted(name, currency)
            frame = frame.loc[frame.index.date >= start]
            if (frame[["Open", "Close"]] <= 0).any().any():
                raise ValueError("The allocation simulation requires positive prices. Choose a period after negative or zero futures prices.")
            params = Parameters(strategy, slow, fast, entry / 100, exit_threshold / 100)
            account = Account(capital, allocation / 100, fee)
            folds = None
            if mode == "Walk-forward":
                ledger, folds = walk_forward(frame, params, account, train, test)
                ledgers = {strategy: ledger}
            else:
                names = STRATEGIES if mode == "Compare strategies" else [strategy]
                ledgers = {s: fixed_run(frame, replace(params, strategy=s), account) for s in names}
            provenance = {**quality(frame), "parameters": asdict(params), "account": asdict(account),
                          "start": start.isoformat(), "mode": mode, "train_sessions": train, "test_sessions": test}
            for ledger in ledgers.values():
                ledger.attrs.update(provenance)
            st.session_state.research_result = (identity, ledgers, folds, provenance)
        except (ValueError, OSError) as error:
            st.error(str(error))
    stored = st.session_state.get("research_result")
    if stored is None or stored[0] != identity:
        return
    _, ledgers, folds, provenance = stored
    first = next(iter(ledgers.values()))
    equity = {s: r.strategy_equity for s, r in ledgers.items()}
    equity["Buy and hold"] = first.benchmark_equity
    plot(equity, currency, "equity")
    table = pd.DataFrame({s: summary(r, currency).loc["Strategy"] for s, r in ledgers.items()}).T
    table.loc["Buy and hold"] = summary(first, currency).loc["Buy and hold"]
    st.dataframe(table.round(3), width="stretch")
    plot({s: r.strategy_drawdown * 100 for s, r in ledgers.items()}, "%", "drawdown")
    st.download_button("Download performance metrics", table.to_csv(index_label="portfolio"), "metrics.csv", "text/csv")
    detail = st.selectbox("Strategy detail", list(ledgers))
    with st.expander("Prices and simulated trades"):
        plot({"Reference close": ledgers[detail]["Close"]}, f"{currency}/{market.unit}",
             "trades", trades=ledgers[detail])
    csv_button(ledgers[detail], "strategy.csv")
    if folds is not None:
        st.dataframe(folds, hide_index=True)
        st.download_button("Download walk-forward folds", folds.to_csv(index=False), "folds.csv")
    with st.expander("Simulation source"):
        st.json(provenance)


st.set_page_config(page_title="Commodity tracker", page_icon="◈", layout="centered")
st.title("Commodity tracker")
currency = st.selectbox("Display currency", CURRENCIES)
if "lots" not in st.session_state:
    st.session_state.lots = []
ticker_board()
name = st.selectbox("Commodity", list(MARKETS))
market = MARKETS[name]
page = st.radio("Section", ["My holdings", "Portfolio", "Price history", "Strategy lab"],
                horizontal=True, label_visibility="collapsed")
with st.spinner("Loading observations…"):
    {"My holdings": holding_editor, "Portfolio": portfolio_page,
     "Price history": price_page, "Strategy lab": strategy_page}[page]()
st.caption("Valuations use observed quotes and stated conversions. Holdings are saved in this session; export your portfolio to retain them.")

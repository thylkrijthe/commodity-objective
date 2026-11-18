"""Interactive charts with visible-window vertical scaling."""

import plotly.graph_objects as go
import streamlit as st
from html import escape


def plot(series, currency, key, resolution="Daily", trades=None):
    figure = go.Figure()
    for name, values in series.items():
        figure.add_scatter(x=[stamp.isoformat() for stamp in values.index], y=values.to_list(), name=escape(str(name)), mode="lines+markers",
                           marker={"size": 3}, line={"width": 2},
                           hovertemplate=f"%{{x|%d %b %Y %H:%M}} UTC<br>%{{y:,.4f}} {currency}<extra>%{{fullData.name}}</extra>")
    if trades is not None:
        for direction, label, symbol in ((1, "Buy at open", "triangle-up"), (-1, "Sell at open", "triangle-down")):
            mask = trades["strategy_trade_notional"] * direction > 0
            figure.add_scatter(
                x=[stamp.isoformat() for stamp in trades.index[mask]], y=trades.loc[mask, "Open"].to_list(),
                name=label, mode="markers", marker={"symbol": symbol, "size": 9},
                hovertemplate=f"%{{x|%d %b %Y}}<br>%{{y:,.4f}} {currency}<extra>{label}</extra>",
            )
    figure.update_layout(
        template="plotly_white", height=420, margin={"l": 65, "r": 15, "t": 15, "b": 55},
        dragmode="zoom", yaxis={"title": currency, "rangemode": "normal", "tickformat": ",.2f"},
        xaxis={"type": "date", "rangeslider": {"visible": True, "thickness": .08}},
        legend={"orientation": "h"}, showlegend=len(series) > 1 or trades is not None,
        colorway=["#176c62", "#ae6d31", "#5a65a0", "#923f58", "#659253", "#695c50", "#368caa", "#aa8e28"],
        paper_bgcolor="#fbfaf7", plot_bgcolor="#fbfaf7",
    )
    # Both slider and zoom changes recompute the y range from real visible observations.
    script = """
const gd = document.getElementById('{plot_id}');
let busy = false;
function scaleVisible() {
  if (busy) return;
  const range = gd.layout.xaxis.range;
  let ys = [];
  gd.data.forEach(trace => {
    if (trace.visible === 'legendonly' || trace.visible === false) return;
    trace.x.forEach((x, i) => {
      const t = new Date(x).getTime();
      if ((!range || (t >= new Date(range[0]).getTime() && t <= new Date(range[1]).getTime())) &&
          Number.isFinite(Number(trace.y[i]))) ys.push(Number(trace.y[i]));
    });
  });
  if (!ys.length) return;
  const lo = ys.reduce((a,b) => Math.min(a,b), Infinity), hi = ys.reduce((a,b) => Math.max(a,b), -Infinity);
  const pad = Math.max((hi - lo) * .12, Math.abs(hi) * .0001, .000001);
  busy = true;
  Plotly.relayout(gd, {'yaxis.range': [lo - pad, hi + pad], 'yaxis.autorange': false})
    .finally(() => busy = false);
}
gd.on('plotly_relayout', ev => {
  if (Object.keys(ev).some(k => k.startsWith('xaxis'))) scaleVisible();
});
gd.on('plotly_restyle', scaleVisible);
scaleVisible();
"""
    html = figure.to_html(full_html=False, include_plotlyjs="cdn", post_script=script,
                          config={"responsive": True, "displaylogo": False, "scrollZoom": True})
    st.iframe(html, height=435, alt="Interactive chart with automatic visible-range scaling")

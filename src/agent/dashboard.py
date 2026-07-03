"""Mission-control dashboard: renders one self-contained docs/index.html.

No JS, no CDN — inline CSS and hand-rolled SVG only, so it renders identically
on GitHub Pages, a phone, or a local file. Regenerated nightly by CI after the
daily loop, and on demand via `python -m agent.dashboard [--open]`.
"""

import sys
import webbrowser
from datetime import date, datetime, timezone
from html import escape
from pathlib import Path

from dotenv import load_dotenv

from agent import data, db
from agent.config import DEADBAND, SMA_WINDOW, STARTING_CAPITAL, STRATEGY_VERSION
from agent.metrics import max_drawdown, sharpe, total_return

# --- palette ---
BG = "#060913"
PANEL = "#0b1224"
BORDER = "#1b2a4a"
TEXT = "#c9d6ee"
DIM = "#5b6b8c"
CYAN = "#38e1ff"
GREEN = "#3ddc97"
RED = "#ff5d73"
AMBER = "#ffc857"
PURPLE = "#8b7bff"

RUN_TARGET_DAYS = 90


# ---------- data ----------

def fetch() -> dict:
    conn = db.client()
    eq = conn.table("equity_daily").select("*").order("date").execute().data
    return {
        "equity": eq,
        "decisions": conn.table("decisions").select("*").order("run_date", desc=True).limit(14).execute().data,
        "trades": conn.table("trades").select("*").order("created_at", desc=True).limit(10).execute().data,
        "events": conn.table("events").select("*").order("created_at", desc=True).limit(10).execute().data,
        "state": {s["system"]: s for s in conn.table("system_state").select("*").execute().data},
        "closes": data.get_daily_closes(SMA_WINDOW + 120),
    }


def series(equity_rows: list[dict], system: str) -> tuple[list[str], list[float]]:
    rows = [r for r in equity_rows if r["system"] == system]
    return [r["date"] for r in rows], [float(r["equity"]) for r in rows]


# ---------- svg helpers ----------

def _scale(pts, w, h, pad, ymin, ymax, n):
    span = (ymax - ymin) or 1.0
    step = (w - 2 * pad) / max(n - 1, 1)
    return [(pad + i * step, h - pad - (v - ymin) / span * (h - 2 * pad)) for i, v in pts]


def _poly(coords, color, width=2.0, dash=""):
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<polyline points="{pts}" fill="none" stroke="{color}" '
            f'stroke-width="{width}" stroke-linejoin="round"{d}/>')


def _dots(coords, color, r=3.5):
    return "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{color}"/>' for x, y in coords)


def _frame(w, h, pad, ymin, ymax, fmt):
    out = []
    for i in range(5):
        y = pad + i * (h - 2 * pad) / 4
        v = ymax - i * (ymax - ymin) / 4
        out.append(f'<line x1="{pad}" y1="{y:.1f}" x2="{w - pad}" y2="{y:.1f}" '
                   f'stroke="{BORDER}" stroke-width="0.6"/>')
        out.append(f'<text x="{w - pad + 6}" y="{y + 3.5:.1f}" fill="{DIM}" '
                   f'font-size="10">{fmt(v)}</text>')
    return "".join(out)


def chart(title: str, subtitle: str, lines: list[tuple[list[float], str, str]],
          bands: list[tuple[list[float], list[float], str]] = (),
          fmt=lambda v: f"{v:,.0f}", w=760, h=250, pad=34) -> str:
    """lines: [(values, color, label)]; bands: [(upper, lower, fill)] drawn behind."""
    allv = [v for vals, _, _ in lines for v in vals]
    allv += [v for up, lo, _ in bands for v in up + lo]
    if not allv:
        return ""
    ymin, ymax = min(allv), max(allv)
    if ymin == ymax:
        ymin, ymax = ymin * 0.995, ymax * 1.005
    ymin -= (ymax - ymin) * 0.06
    ymax += (ymax - ymin) * 0.06
    n = max(len(vals) for vals, _, _ in lines)

    body = [_frame(w, h, pad, ymin, ymax, fmt)]
    for up, lo, fill in bands:
        cu = _scale(list(enumerate(up)), w, h, pad, ymin, ymax, n)
        cl = _scale(list(enumerate(lo)), w, h, pad, ymin, ymax, n)
        path = " ".join(f"{x:.1f},{y:.1f}" for x, y in cu + cl[::-1])
        body.append(f'<polygon points="{path}" fill="{fill}"/>')
    for vals, color, _ in lines:
        coords = _scale(list(enumerate(vals)), w, h, pad, ymin, ymax, n)
        body.append(_poly(coords, color) if len(coords) > 1 else _dots(coords, color))

    legend = " ".join(
        f'<span class="lg"><i style="background:{c}"></i>{escape(lb)}</span>'
        for _, c, lb in lines if lb
    )
    return f"""<div class="panel">
      <div class="ph"><span class="pt">{escape(title)}</span><span class="ps">{escape(subtitle)}</span><span class="legend">{legend}</span></div>
      <svg viewBox="0 0 {w} {h}" preserveAspectRatio="none">{''.join(body)}</svg>
    </div>"""


# ---------- html pieces ----------

def tile(label: str, value: str, tone: str = TEXT, sub: str = "") -> str:
    return (f'<div class="tile"><div class="tl">{escape(label)}</div>'
            f'<div class="tv" style="color:{tone}">{value}</div>'
            f'<div class="ts">{escape(sub)}</div></div>')


def fmt_money(v: float) -> str:
    return f"${v:,.0f}"


def fmt_pct(v: float, signed=True) -> str:
    return f"{v:+.2%}" if signed else f"{v:.2%}"


def build_html(d: dict) -> str:
    now = datetime.now(timezone.utc)
    s_dates, s_eq = series(d["equity"], "strategy")
    b_dates, b_eq = series(d["equity"], "baseline")
    st = d["state"].get("strategy", {})
    latest_dec = d["decisions"][0] if d["decisions"] else None

    # status
    position = st.get("position", "?").upper()
    kill = bool(st.get("kill_switch_tripped"))
    halted = st.get("halted_until") is not None and st["halted_until"] > now.isoformat()
    day_n = len(s_eq)
    last_run = s_dates[-1] if s_dates else None
    stale = last_run is not None and (now.date() - date.fromisoformat(last_run)).days > 2

    if kill:
        sys_status, sys_tone = "KILL SWITCH", RED
    elif halted:
        sys_status, sys_tone = "HALTED 24H", AMBER
    elif stale:
        sys_status, sys_tone = "STALE DATA", AMBER
    else:
        sys_status, sys_tone = "NOMINAL", GREEN

    cur_s = s_eq[-1] if s_eq else STARTING_CAPITAL
    cur_b = b_eq[-1] if b_eq else STARTING_CAPITAL
    delta = cur_s - cur_b
    s_full = [STARTING_CAPITAL] + s_eq  # include inception so return-to-date is honest
    b_full = [STARTING_CAPITAL] + b_eq

    tiles = "".join([
        tile("SYSTEM", sys_status, sys_tone,
             f"last bar {last_run or '—'}" + (" ⚠ check scheduler" if stale else "")),
        tile("POSITION", position, CYAN if position == "LONG" else DIM,
             f"{float(st.get('qty', 0)):.6f} BTC" if position == "LONG" else "100% cash"),
        tile("STRATEGY EQUITY", fmt_money(cur_s),
             GREEN if cur_s >= STARTING_CAPITAL else RED, fmt_pct(total_return(s_full))),
        tile("VS BASELINE", f"{delta:+,.0f}", GREEN if delta >= 0 else RED,
             f"baseline {fmt_money(cur_b)}"),
        tile("DRAWDOWN", fmt_pct(-max_drawdown(s_full), signed=False),
             GREEN if max_drawdown(s_full) < 0.10 else AMBER,
             f"baseline {fmt_pct(-max_drawdown(b_full), signed=False)}"),
        tile("MISSION DAY", f"{day_n:02d} / {RUN_TARGET_DAYS}", PURPLE,
             f"{STRATEGY_VERSION} · paper only"),
    ])

    # scoreboard: the three PRD success criteria
    sh_s, sh_b = sharpe(s_full), sharpe(b_full)
    enough = day_n >= 7
    score = f"""<div class="panel"><div class="ph"><span class="pt">SUCCESS CRITERIA</span>
      <span class="ps">strategy must beat baseline after costs · needs ≥{7} days for meaningful stats</span></div>
      <table><tr><th></th><th>STRATEGY</th><th>BASELINE</th><th>VERDICT</th></tr>
      <tr><td>Return after costs</td><td>{fmt_pct(total_return(s_full))}</td><td>{fmt_pct(total_return(b_full))}</td>
      <td style="color:{GREEN if total_return(s_full) >= total_return(b_full) else RED}">{'AHEAD' if total_return(s_full) >= total_return(b_full) else 'BEHIND'}</td></tr>
      <tr><td>Sharpe (ann.)</td><td>{f'{sh_s:.2f}' if enough else '—'}</td><td>{f'{sh_b:.2f}' if enough else '—'}</td>
      <td style="color:{DIM if not enough else GREEN if sh_s >= sh_b else RED}">{'TOO EARLY' if not enough else 'AHEAD' if sh_s >= sh_b else 'BEHIND'}</td></tr>
      <tr><td>Max drawdown</td><td>{fmt_pct(-max_drawdown(s_full), signed=False)}</td><td>{fmt_pct(-max_drawdown(b_full), signed=False)}</td>
      <td style="color:{GREEN if max_drawdown(s_full) <= max_drawdown(b_full) else RED}">{'SMALLER' if max_drawdown(s_full) <= max_drawdown(b_full) else 'LARGER'}</td></tr>
      </table></div>"""

    # charts
    closes = d["closes"]
    prices = [c for _, c in closes]
    smas = [sum(prices[i - SMA_WINDOW + 1: i + 1]) / SMA_WINDOW
            for i in range(SMA_WINDOW - 1, len(prices))]
    tail_p = prices[-len(smas):]
    upper = [s * (1 + DEADBAND) for s in smas]
    lower = [s * (1 - DEADBAND) for s in smas]
    price_chart = chart(
        "BTC/USD vs SMA-50", f"last {len(smas)} daily closes · deadband ±{DEADBAND:.0%} shaded",
        [(tail_p, CYAN, "price"), (smas, AMBER, "sma-50")],
        bands=[(upper, lower, "rgba(255,200,87,0.10)")],
        fmt=lambda v: f"{v / 1000:,.0f}k",
    )
    equity_chart = chart(
        "EQUITY CURVES", "simulated ledgers · identical cost model",
        [(s_eq or [STARTING_CAPITAL], GREEN, "strategy"), (b_eq or [STARTING_CAPITAL], DIM, "baseline")],
        fmt=lambda v: f"{v / 1000:,.1f}k",
    )

    def dd_series(eqs):
        peak, out = -1e18, []
        for e in eqs:
            peak = max(peak, e)
            out.append(-(peak - e) / peak * 100)
        return out
    dd_chart = chart(
        "DRAWDOWN FROM PEAK", "% below high-water mark",
        [(dd_series(s_full), GREEN, "strategy"), (dd_series(b_full), RED, "baseline")],
        fmt=lambda v: f"{v:.1f}%",
        h=180,
    )

    # tables
    def table(title, headers, rows, empty):
        body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) \
            or f'<tr><td colspan="{len(headers)}" style="color:{DIM}">{escape(empty)}</td></tr>'
        head = "".join(f"<th>{h}</th>" for h in headers)
        return (f'<div class="panel"><div class="ph"><span class="pt">{escape(title)}</span></div>'
                f'<table><tr>{head}</tr>{body}</table></div>')

    dec_rows = [[
        r["run_date"],
        f'{float(r["price"]):,.0f}',
        f'{float(r["sma_50"]):,.0f}',
        f'<span style="color:{ {"buy": GREEN, "sell": RED}.get(r["signal"], DIM) }">{r["signal"].upper()}</span>',
        "◈" if r["in_deadband"] else "",
        r["action_taken"] + (f' · {escape(r["block_reason"])}' if r.get("block_reason") else ""),
    ] for r in d["decisions"]]

    trade_rows = [[
        r["created_at"][:10],
        f'<span style="color:{GREEN if r["side"] == "buy" else RED}">{r["side"].upper()}</span>',
        f'{float(r["qty"]):.6f}',
        f'{float(r["price"]):,.0f}',
        f'{float(r["fee_paid"]):,.2f}',
        f'{float(r["account_value_after"]):,.0f}',
    ] for r in d["trades"]]

    event_rows = [[r["created_at"][:16].replace("T", " "), r["kind"], escape(r.get("detail") or "")]
                  for r in d["events"]]

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TREND AGENT · MISSION CONTROL</title>
<style>
  * {{ box-sizing: border-box; margin: 0; }}
  body {{ background: {BG}; color: {TEXT};
    font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    padding: 18px; max-width: 1200px; margin: 0 auto;
    background-image: radial-gradient(ellipse 80% 50% at 50% -10%, rgba(56,225,255,0.07), transparent),
                      radial-gradient(ellipse 60% 40% at 90% 110%, rgba(139,123,255,0.06), transparent); }}
  header {{ display: flex; justify-content: space-between; align-items: baseline;
    border-bottom: 1px solid {BORDER}; padding-bottom: 12px; margin-bottom: 16px; flex-wrap: wrap; gap: 6px; }}
  h1 {{ font-size: 15px; letter-spacing: 3px; color: {CYAN};
    text-shadow: 0 0 18px rgba(56,225,255,0.45); }}
  h1 b {{ color: {TEXT}; font-weight: 400; }}
  .stamp {{ color: {DIM}; font-size: 11px; letter-spacing: 1px; }}
  .tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 10px; margin-bottom: 14px; }}
  .tile {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px; padding: 12px 14px; }}
  .tl {{ font-size: 10px; letter-spacing: 2px; color: {DIM}; }}
  .tv {{ font-size: 22px; margin: 4px 0 2px; letter-spacing: 0.5px; }}
  .ts {{ font-size: 11px; color: {DIM}; }}
  .panel {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 12px 14px; margin-bottom: 14px; overflow-x: auto; }}
  .ph {{ display: flex; gap: 12px; align-items: baseline; margin-bottom: 8px; flex-wrap: wrap; }}
  .pt {{ font-size: 11px; letter-spacing: 2px; color: {CYAN}; }}
  .ps {{ font-size: 11px; color: {DIM}; }}
  .legend {{ margin-left: auto; font-size: 11px; color: {DIM}; }}
  .lg i {{ display: inline-block; width: 9px; height: 9px; border-radius: 2px;
    margin: 0 5px 0 12px; vertical-align: -1px; }}
  svg {{ width: 100%; height: auto; display: block; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  th {{ text-align: left; color: {DIM}; font-weight: 400; font-size: 10px; letter-spacing: 1.5px;
    border-bottom: 1px solid {BORDER}; padding: 4px 10px 6px 0; }}
  td {{ padding: 5px 10px 5px 0; border-bottom: 1px solid rgba(27,42,74,0.5); }}
  footer {{ color: {DIM}; font-size: 10px; letter-spacing: 1px; margin-top: 18px; text-align: center; }}
</style></head><body>
<header><h1>⬢ TREND AGENT <b>// MISSION CONTROL</b></h1>
<span class="stamp">GENERATED {now.strftime('%Y-%m-%d %H:%M UTC')} · {STRATEGY_VERSION} · PAPER TRADING</span></header>
<div class="tiles">{tiles}</div>
{score}
{equity_chart}
{price_chart}
{dd_chart}
{table("DECISION LOG", ["BAR DATE", "CLOSE", "SMA-50", "SIGNAL", "BAND", "ACTION"], dec_rows, "no decisions yet")}
{table("TRADES", ["DATE", "SIDE", "QTY BTC", "PRICE", "COSTS", "EQUITY AFTER"], trade_rows, "no trades yet — waiting for a signal to clear the deadband")}
{table("EVENTS", ["TIME", "KIND", "DETAIL"], event_rows, "no events")}
<footer>AUTONOMOUS · RISK-GATED · COST-AWARE — RULE DECIDES, HUMANS REVIEW WEEKLY · NOT FINANCIAL ADVICE</footer>
</body></html>"""


def main() -> None:
    load_dotenv()
    html = build_html(fetch())
    out = Path(__file__).resolve().parents[2] / "docs" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html)
    print(f"wrote {out} ({len(html):,} bytes)")
    if "--open" in sys.argv:
        webbrowser.open(out.as_uri())


if __name__ == "__main__":
    main()

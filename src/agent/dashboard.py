"""Swarm mission control: renders one self-contained docs/index.html.

No JS, no CDN — inline CSS and hand-rolled SVG only. Regenerated nightly by CI
after the daily loop, and on demand via `python -m agent.dashboard [--open]`.

HOUSTON (the overseer) is a scoreboard and referee: it compares, it flags,
it never allocates capital.
"""

import sys
import webbrowser
from datetime import date, datetime, timezone
from html import escape
from pathlib import Path

from dotenv import load_dotenv

from agent import data, db, signal
from agent.config import (BREAKOUT_ENTRY, BREAKOUT_EXIT, RSI_BUY, RSI_PERIOD,
                          RSI_SELL, SMA_WINDOW, STARTING_CAPITAL)
from agent.metrics import max_drawdown, sharpe, total_return
from agent.strategies import AGENTS, BASELINE_KEY, MAX_WARMUP

# --- palette: blacks and charcoal, neon accents ---
BG = "#08080a"
PANEL = "#121214"
BORDER = "#242428"
TEXT = "#d8d8dc"
DIM = "#6e6e78"
CYAN = "#3ce0ff"
GREEN = "#3ddc97"
RED = "#ff5d73"
AMBER = "#ffc857"
PURPLE = "#8b7bff"

RUN_TARGET_DAYS = 90
HOUSTON = {"name": "HOUSTON", "color": "#8a8a94", "color_dark": "#45454d", "accessory": "headset"}


# ---------- data ----------

def fetch() -> dict:
    conn = db.client()
    return {
        "equity": conn.table("equity_daily").select("*").order("date").execute().data,
        "decisions": conn.table("decisions").select("*").order("run_date", desc=True).limit(24).execute().data,
        "trades": conn.table("trades").select("*").order("created_at", desc=True).limit(12).execute().data,
        "events": conn.table("events").select("*").order("created_at", desc=True).limit(8).execute().data,
        "reviews": conn.table("daily_review").select("*").eq("rules_followed", False).execute().data,
        "state": {s["agent"]: s for s in conn.table("system_state").select("*").execute().data},
        "closes": data.get_daily_closes(MAX_WARMUP + 120),
    }


def series(equity_rows: list[dict], agent: str) -> list[float]:
    return [float(r["equity"]) for r in equity_rows if r["agent"] == agent]


# ---------- svg chart helpers (unchanged mechanics) ----------

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


def chart(title, subtitle, lines, bands=(), fmt=lambda v: f"{v:,.0f}", w=760, h=250, pad=34):
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


# ---------- the monster rig ----------

MOOD_STYLE = {
    "happy":    (GREEN, (0.10, 0),   "WINNING"),
    "neutral":  (CYAN,  (0.38, -10), "SCHEMING"),
    "sad":      (RED,   (0.58, 8),   "ENDURING"),
    "worried":  (AMBER, (0.16, -4),  "ON EDGE"),
    "critical": (RED,   (0.0, 0),    "SHUT DOWN"),
}

_ACCESSORIES = {
    "horns": ('<path d="M44 40 Q39 24 33 20 Q44 23 52 34 Z" fill="{m}" stroke="{i}" stroke-width="2"/>'
              '<path d="M96 40 Q101 24 107 20 Q96 23 88 34 Z" fill="{m}" stroke="{i}" stroke-width="2"/>'),
    "antenna": ('<line x1="70" y1="30" x2="70" y2="12" stroke="{m}" stroke-width="3"/>'
                '<path d="M63 14 L70 4 L77 14 Z" fill="{m}" stroke="{i}" stroke-width="2"/>'),
    "shell": ('<path d="M34 46 A40 40 0 0 1 106 46" fill="none" stroke="{i}" stroke-width="7"/>'
              '<path d="M34 46 A40 40 0 0 1 106 46" fill="none" stroke="{m}" stroke-width="4"/>'
              '<path d="M52 22 L58 32 M70 18 L70 30 M88 22 L82 32" stroke="{m}" stroke-width="3"/>'),
    "droop": ('<path d="M40 38 Q28 40 26 52 Q34 48 46 46 Z" fill="{m}" stroke="{i}" stroke-width="2"/>'
              '<path d="M100 38 Q112 40 114 52 Q106 48 94 46 Z" fill="{m}" stroke="{i}" stroke-width="2"/>'),
    "headset": ('<path d="M34 52 A38 38 0 0 1 106 52" fill="none" stroke="{i}" stroke-width="6"/>'
                '<rect x="26" y="50" width="10" height="16" rx="4" fill="{m}" stroke="{i}" stroke-width="2"/>'
                '<rect x="104" y="50" width="10" height="16" rx="4" fill="{m}" stroke="{i}" stroke-width="2"/>'
                '<path d="M32 66 Q30 84 46 92" fill="none" stroke="{m}" stroke-width="3"/>'
                '<circle cx="49" cy="93" r="4" fill="{m}" stroke="{i}" stroke-width="1.5"/>'),
}


def _mouth(mood: str) -> str:
    ink, teeth = "#0b0b0c", "#e9e7dc"
    if mood == "happy":
        return (f'<path d="M34 100 Q70 121 106 100 Q70 134 34 100 Z" fill="{ink}"/>'
                f'<path d="M38 103 L46 111 L54 104 L62 112 L70 104 L78 112 L86 104 '
                f'L94 111 L102 103" stroke="{teeth}" stroke-width="3" fill="none" '
                f'stroke-linejoin="round"/>')
    if mood == "neutral":
        return (f'<path d="M52 106 Q76 118 102 101" stroke="{ink}" stroke-width="4.5" '
                f'fill="none" stroke-linecap="round"/>'
                f'<path d="M78 109 L84 115 L89 107 L95 112 L99 103" stroke="{teeth}" '
                f'stroke-width="3" fill="none" stroke-linejoin="round"/>')
    if mood == "sad":
        return (f'<path d="M46 115 Q70 99 94 115" stroke="{ink}" stroke-width="4.5" '
                f'fill="none" stroke-linecap="round"/>')
    if mood == "worried":
        return (f'<path d="M46 110 Q54 103 62 110 Q70 117 78 110 Q86 103 94 110" '
                f'stroke="{ink}" stroke-width="4" fill="none" stroke-linecap="round"/>')
    return (f'<rect x="42" y="101" width="56" height="13" rx="3.5" fill="{ink}"/>'
            f'<path d="M52 101 V114 M62 101 V114 M72 101 V114 M82 101 V114 M92 101 V114" '
            f'stroke="{teeth}" stroke-width="2.2"/>')


def _eye(mood: str, accent: str, uid: str, lid_fill: str) -> str:
    socket = ('<circle cx="70" cy="64" r="23" fill="#eceadf" '
              'stroke="#0b0b0c" stroke-width="3"/>')
    if mood == "critical":
        return socket + (f'<path d="M56 50 L84 78 M84 50 L56 78" stroke="{RED}" '
                         f'stroke-width="5" stroke-linecap="round"/>')
    lid_frac, lid_tilt = MOOD_STYLE[mood][1]
    lid_h = 4 + lid_frac * 46
    pupil = (f'<circle cx="72" cy="66" r="10" fill="{accent}"/>'
             f'<circle cx="72" cy="66" r="4.5" fill="#0b0b0c"/>'
             f'<circle cx="68" cy="61" r="2.6" fill="#f4f2e8"/>')
    lid = (f'<g clip-path="url(#eye-{uid})"><rect x="42" y="38" width="56" height="{lid_h:.0f}" '
           f'fill="{lid_fill}" stroke="#0b0b0c" stroke-width="2.5" '
           f'transform="rotate({lid_tilt} 70 64)"/></g>')
    return socket + pupil + lid


def monster_svg(mood: str, uid: str, color: str, color_dark: str, accessory: str) -> str:
    accent = MOOD_STYLE[mood][0]
    metal, ink = "#3b3b42", "#0b0b0c"
    acc = _ACCESSORIES[accessory].format(m=metal, i=ink)
    return f"""<svg viewBox="0 0 140 152" class="monster" role="img" aria-label="{uid} is {mood}">
      <defs>
        <radialGradient id="body-{uid}" cx="38%" cy="30%" r="80%">
          <stop offset="0%" stop-color="{color}"/>
          <stop offset="100%" stop-color="{color_dark}"/>
        </radialGradient>
        <clipPath id="eye-{uid}"><circle cx="70" cy="64" r="23"/></clipPath>
      </defs>
      <ellipse cx="70" cy="147" rx="35" ry="4.5" fill="rgba(0,0,0,0.5)"/>
      <path d="M54 120 L49 139" stroke="{metal}" stroke-width="8" stroke-linecap="round"/>
      <path d="M86 120 L91 139" stroke="{metal}" stroke-width="8" stroke-linecap="round"/>
      <rect x="36" y="136" width="24" height="10" rx="5" fill="{metal}" stroke="{ink}" stroke-width="2"/>
      <rect x="80" y="136" width="24" height="10" rx="5" fill="{metal}" stroke="{ink}" stroke-width="2"/>
      <path d="M28 84 Q13 92 11 106" stroke="{metal}" stroke-width="6.5" fill="none" stroke-linecap="round"/>
      <circle cx="11" cy="106" r="4.5" fill="#4c4c55"/>
      <path d="M11 106 Q9 120 17 128" stroke="{metal}" stroke-width="6" fill="none" stroke-linecap="round"/>
      <circle cx="19" cy="131" r="7.5" fill="{metal}" stroke="{ink}" stroke-width="2"/>
      <path d="M112 84 Q127 92 129 106" stroke="{metal}" stroke-width="6.5" fill="none" stroke-linecap="round"/>
      <circle cx="129" cy="106" r="4.5" fill="#4c4c55"/>
      <path d="M129 106 Q131 120 123 128" stroke="{metal}" stroke-width="6" fill="none" stroke-linecap="round"/>
      <circle cx="121" cy="131" r="7.5" fill="{metal}" stroke="{ink}" stroke-width="2"/>
      <circle cx="70" cy="78" r="46" fill="url(#body-{uid})" stroke="{ink}" stroke-width="3"/>
      {acc}
      <rect x="52" y="28" width="36" height="9" rx="3.5" fill="{color_dark}" stroke="{ink}" stroke-width="2"/>
      {_eye(mood, accent, uid, color_dark)}
      {_mouth(mood)}
    </svg>"""


# ---------- moods ----------

def agent_mood(strat, kill, halted, stale, position, day_ret, base_day):
    if kill:
        return ("critical", "Emergency stop.",
                "My account fell more than 25% below start, so I shut myself down. "
                "A human has to review me before I trade again.")
    if halted:
        return ("worried", "Taking a breather.",
                "I lost more than 10% in one day — the safety rules benched me for 24 hours.")
    if stale:
        return ("worried", "Am I stuck?",
                "No run logged in over two days. Someone check the scheduler.")
    if day_ret is None:
        return ("neutral", "First day on the job.", strat.flat_text if position == "flat" else strat.long_text)
    if position == "flat" and base_day is not None and base_day < -0.01:
        return ("happy", f"Dodged a {base_day:.1%} drop.",
                "Bitcoin fell today and I'm safely in cash. " + strat.flat_text)
    if day_ret > 0.005:
        return ("happy", f"Up {day_ret:+.1%} today.", strat.long_text)
    if day_ret < -0.005:
        return ("sad", f"Down {day_ret:+.1%} today.",
                "Single days are noise, and my rule hasn't triggered. " + strat.long_text)
    return ("neutral",
            "In cash, watching." if position == "flat" else "Holding steady.",
            strat.flat_text if position == "flat" else strat.long_text)


# ---------- page ----------

def fmt_money(v): return f"${v:,.0f}"
def fmt_pct(v, signed=True): return f"{v:+.2%}" if signed else f"{v:.2%}"


def build_html(d: dict) -> str:
    now = datetime.now(timezone.utc)
    eq_rows = d["equity"]
    curves = {k: series(eq_rows, k) for k in [*AGENTS, BASELINE_KEY]}
    full = {k: [STARTING_CAPITAL] + v for k, v in curves.items()}
    dates = sorted({r["date"] for r in eq_rows})
    day_n = len(dates)
    last_run = dates[-1] if dates else None
    stale = last_run is not None and (now.date() - date.fromisoformat(last_run)).days > 2
    b_eq = curves[BASELINE_KEY][-1] if curves[BASELINE_KEY] else STARTING_CAPITAL
    b_day = (full[BASELINE_KEY][-1] / full[BASELINE_KEY][-2] - 1) if len(full[BASELINE_KEY]) >= 2 else None
    enough = day_n >= 7

    # per-agent stats + moods
    stats, moods = {}, {}
    for key, strat in AGENTS.items():
        st = d["state"].get(key, {})
        cur = curves[key][-1] if curves[key] else STARTING_CAPITAL
        day_ret = (full[key][-1] / full[key][-2] - 1) if len(full[key]) >= 2 else None
        kill = bool(st.get("kill_switch_tripped"))
        halted = st.get("halted_until") is not None and st["halted_until"] > now.isoformat()
        moods[key] = agent_mood(strat, kill, halted, stale, st.get("position", "flat"), day_ret, b_day)
        stats[key] = {
            "equity": cur, "ret": total_return(full[key]), "vs_base": cur - b_eq,
            "dd": max_drawdown(full[key]), "sharpe": sharpe(full[key]),
            "position": st.get("position", "flat"), "kill": kill, "halted": halted,
        }

    # HOUSTON's verdict
    leader_key = max(stats, key=lambda k: stats[k]["equity"])
    leader = AGENTS[leader_key]
    beating = sum(1 for s in stats.values() if s["equity"] >= b_eq)
    flags = [f"{AGENTS[k].name} kill-switched" for k, s in stats.items() if s["kill"]]
    flags += [f"{AGENTS[k].name} in timeout" for k, s in stats.items() if s["halted"]]
    flags += [f"{len(d['reviews'])} rule violations logged"] if d["reviews"] else []
    if stale:
        flags.append("data stale — check scheduler")
    houston_mood = "critical" if any(s["kill"] for s in stats.values()) else \
        "worried" if flags else ("neutral" if day_n < 7 else
                                 ("happy" if beating >= 2 else "sad"))
    gap = stats[leader_key]["equity"] - b_eq
    houston_line = (f"Day {day_n} of {RUN_TARGET_DAYS}. {leader.name} leads at "
                    f"{fmt_money(stats[leader_key]['equity'])} ({gap:+,.0f} vs the lazy rival). "
                    f"{beating} of {len(AGENTS)} monsters are beating buy-and-hold. "
                    + ("Flags: " + "; ".join(flags) + "." if flags else "All rules obeyed, no flags."))
    houston = f"""<div class="panel kp">
      {monster_svg(houston_mood, "houston", HOUSTON["color"], HOUSTON["color_dark"], "headset")}
      <div class="bubble" style="border-color:{MOOD_STYLE[houston_mood][0]}">
        <div class="kname">HOUSTON · MISSION OVERSEER <span style="color:{DIM}">— watches, compares, never trades</span></div>
        <div class="khead">{escape(houston_line)}</div>
        <div class="kdetail">Reminder: with four racers, the current leader is partly lucky.
        Everyone is judged against the baseline and their own pre-registered expectation at day {RUN_TARGET_DAYS} — not against each other's hot streaks.</div>
      </div>
    </div>"""

    # leaderboard
    def lb_row(key):
        if key == BASELINE_KEY:
            name, color, s = "BASELINE (lazy rival)", DIM, {
                "equity": b_eq, "ret": total_return(full[BASELINE_KEY]),
                "vs_base": 0.0, "dd": max_drawdown(full[BASELINE_KEY]),
                "sharpe": sharpe(full[BASELINE_KEY]),
                "position": d["state"].get(BASELINE_KEY, {}).get("position", "long"),
            }
            chip = ""
        else:
            name, color, s = AGENTS[key].name, AGENTS[key].color, stats[key]
            m = moods[key][0]
            chip = f'<span class="chip" style="color:{MOOD_STYLE[m][0]};border-color:{MOOD_STYLE[m][0]}">{MOOD_STYLE[m][2]}</span>'
        vs = f'<span style="color:{GREEN if s["vs_base"] >= 0 else RED}">{s["vs_base"]:+,.0f}</span>' \
            if key != BASELINE_KEY else "—"
        sharpe_cell = f"{s['sharpe']:.2f}" if enough else "—"
        return (f'<tr><td><i class="dot" style="background:{color}"></i>{name}</td>'
                f'<td>{fmt_money(s["equity"])}</td><td>{fmt_pct(s["ret"])}</td><td>{vs}</td>'
                f'<td>{fmt_pct(-s["dd"], signed=False)}</td>'
                f'<td>{sharpe_cell}</td>'
                f'<td>{s["position"].upper()}</td><td>{chip}</td></tr>')

    order = sorted(AGENTS, key=lambda k: -stats[k]["equity"]) + [BASELINE_KEY]
    leaderboard = f"""<div class="panel"><div class="ph"><span class="pt">LEADERBOARD</span>
      <span class="ps">everyone started with $100k on the same day · Sharpe appears after 7 days</span></div>
      <table><tr><th>AGENT</th><th>EQUITY</th><th>RETURN</th><th>VS RIVAL</th><th>WORST SLIDE</th><th>SHARPE</th><th>POSITION</th><th>MOOD</th></tr>
      {''.join(lb_row(k) for k in order)}</table></div>"""

    # swarm equity chart
    swarm_lines = [(curves[k] or [STARTING_CAPITAL], AGENTS[k].color, AGENTS[k].name) for k in AGENTS]
    swarm_lines.append((curves[BASELINE_KEY] or [STARTING_CAPITAL], DIM, "baseline"))
    swarm_chart = chart("THE RACE", "account value, day by day — the whole point of the experiment in one picture",
                        swarm_lines, fmt=lambda v: f"{v / 1000:,.1f}k")

    # monster cards
    cards = []
    for key, strat in AGENTS.items():
        mood, headline, detail = moods[key]
        s = stats[key]
        accent = MOOD_STYLE[mood][0]
        cards.append(f"""<div class="card">
          <div class="cardtop">{monster_svg(mood, key, strat.color, strat.color_dark, strat.accessory)}
            <div><div class="kname">{strat.name} <span class="chip" style="color:{accent};border-color:{accent}">{MOOD_STYLE[mood][2]}</span></div>
            <div class="belief">"{escape(strat.belief)}"</div>
            <div class="rule">{escape(strat.rule)}</div></div></div>
          <div class="khead" style="font-size:14px">{escape(headline)}</div>
          <div class="kdetail">{escape(detail)}</div>
          <div class="statrow">
            <span>{fmt_money(s['equity'])}</span>
            <span style="color:{GREEN if s['vs_base'] >= 0 else RED}">{s['vs_base']:+,.0f} vs rival</span>
            <span>{s['position'].upper()}</span>
          </div></div>""")
    monster_grid = f'<div class="grid">{"".join(cards)}</div>'

    # market context: price + all rule levels, RSI strip
    closes = d["closes"]
    prices = [c for _, c in closes]
    smas = [sum(prices[i - SMA_WINDOW + 1:i + 1]) / SMA_WINDOW for i in range(SMA_WINDOW - 1, len(prices))]
    n_tail = len(smas)
    tail = prices[-n_tail:]
    hi20 = [max(prices[i - BREAKOUT_ENTRY:i]) for i in range(len(prices) - n_tail, len(prices))]
    lo10 = [min(prices[i - BREAKOUT_EXIT:i]) for i in range(len(prices) - n_tail, len(prices))]
    market = chart(
        "THE MARKET", "BTC daily closes with each monster's key levels — amber: KEPLER's trend line · teal: DONNIE's breakout/exit rails",
        [(tail, TEXT, "price"), (smas, AMBER, "sma-50"),
         (hi20, "#3aaea0", "20d high"), (lo10, "#1d5f58", "10d low")],
        fmt=lambda v: f"{v / 1000:,.0f}k")
    rsis = [signal.rsi_wilder(prices[:i + 1], RSI_PERIOD) for i in range(len(prices) - n_tail, len(prices))]
    rsi_chart = chart(
        "DIP'S FEAR GAUGE (RSI-14)", f"below {RSI_BUY} = panic, DIP buys · above {RSI_SELL} = relief, DIP sells",
        [(rsis, PURPLE, "rsi")], bands=[([RSI_SELL] * n_tail, [RSI_BUY] * n_tail, "rgba(154,123,224,0.10)")],
        fmt=lambda v: f"{v:.0f}", h=160)

    # combined logs
    def table(title, subtitle, headers, rows, empty):
        body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) \
            or f'<tr><td colspan="{len(headers)}" style="color:{DIM}">{escape(empty)}</td></tr>'
        head = "".join(f"<th>{h}</th>" for h in headers)
        return (f'<div class="panel"><div class="ph"><span class="pt">{escape(title)}</span>'
                f'<span class="ps">{escape(subtitle)}</span></div>'
                f'<table><tr>{head}</tr>{body}</table></div>')

    def agent_dot(key):
        color = AGENTS[key].color if key in AGENTS else DIM
        name = AGENTS[key].name if key in AGENTS else key.upper()
        return f'<i class="dot" style="background:{color}"></i>{name}'

    dec_rows = [[
        r["run_date"], agent_dot(r["agent"]), f'{float(r["price"]):,.0f}',
        escape(", ".join(f"{k} {v}" for k, v in (r.get("indicators") or {}).items())),
        f'<span style="color:{ {"buy": GREEN, "sell": RED}.get(r["signal"], DIM) }">{r["signal"].upper()}</span>',
        r["action_taken"] + (f' · {escape(r["block_reason"])}' if r.get("block_reason") else ""),
    ] for r in d["decisions"]]

    trade_rows = [[
        r["created_at"][:10], agent_dot(r["agent"]),
        f'<span style="color:{GREEN if r["side"] == "buy" else RED}">{r["side"].upper()}</span>',
        f'{float(r["qty"]):.6f}', f'{float(r["price"]):,.0f}',
        f'{float(r["fee_paid"]):,.2f}', f'{float(r["account_value_after"]):,.0f}',
    ] for r in d["trades"]]

    event_rows = [[r["created_at"][:16].replace("T", " "), r["kind"], escape(r.get("detail") or "")]
                  for r in d["events"]]

    # docs
    roster_lines = "".join(
        f'<p><b>{s.name}</b> — {escape(s.rule)}. Betting that <i>{escape(s.belief.lower())}</i>.</p>'
        for s in AGENTS.values())
    docs = f"""<details class="panel docs"><summary>WHAT AM I LOOKING AT? — the swarm, in plain English</summary>
      <p><b>The experiment.</b> Four robot monsters each trade a pretend $100,000 using one simple,
      locked-in rule. They check the Bitcoin price once a day at 10:05am Brisbane time, make one
      decision, and sleep. Most days: nothing. Expect a trade or two a month each. All of them race
      the <b>lazy rival</b> — a baseline that bought Bitcoin on day one and never touches it.</p>
      {roster_lines}
      <p><b>HOUSTON</b> — the grey one — never trades. It keeps score, flags broken rules, and
      reminds us of the fine print below.</p>
      <p><b>The fine print.</b> With four racers, whoever's on top is partly just lucky — like the
      luckiest of four coin-flippers. So nobody gets judged on the leaderboard alone: each monster
      passes or fails against the baseline and its own backtest expectation after {RUN_TARGET_DAYS}
      days. Rules were locked before launch and never tuned mid-race. Every trade pays realistic
      fees (0.35%). Safety rails on everyone: lose &gt;10% in a day → 24h bench;
      fall 25% below start → shut down until a human looks. <b>No real money anywhere.</b></p>
    </details>"""

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>THE SWARM · MISSION CONTROL</title>
<style>
  * {{ box-sizing: border-box; margin: 0; }}
  body {{ background: {BG}; color: {TEXT};
    font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-variant-numeric: tabular-nums;
    padding: 18px; max-width: 1200px; margin: 0 auto;
    background-image: radial-gradient(ellipse 70% 45% at 50% -10%, rgba(61,220,151,0.06), transparent),
                      radial-gradient(ellipse 55% 40% at 95% 110%, rgba(139,123,255,0.05), transparent); }}
  header {{ border-bottom: 1px solid {BORDER}; padding-bottom: 12px; margin-bottom: 16px; }}
  h1 {{ font-size: 16px; letter-spacing: 4px; color: {GREEN};
    text-shadow: 0 0 20px rgba(61,220,151,0.5); }}
  h1 b {{ color: {DIM}; font-weight: 400; letter-spacing: 3px; }}
  .panel {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px;
    padding: 13px 15px; margin-bottom: 14px; overflow-x: auto;
    box-shadow: 0 8px 22px rgba(0,0,0,0.35); }}
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
  td {{ padding: 5px 10px 5px 0; border-bottom: 1px solid rgba(36,36,40,0.6); white-space: nowrap; }}
  .dot {{ display: inline-block; width: 9px; height: 9px; border-radius: 50%;
    margin-right: 7px; vertical-align: -1px; }}
  .chip {{ font-size: 9px; letter-spacing: 1.5px; border: 1px solid; border-radius: 20px;
    padding: 1.5px 8px; vertical-align: 1px; }}
  .kp {{ display: flex; gap: 16px; align-items: center; }}
  .kp .monster {{ width: 110px; min-width: 110px; }}
  .bubble {{ border: 1px solid; border-radius: 10px; padding: 10px 14px; position: relative; flex: 1; }}
  .bubble::before {{ content: ""; position: absolute; left: -7px; top: 42%;
    width: 12px; height: 12px; background: {PANEL}; border-left: 1px solid;
    border-bottom: 1px solid; border-color: inherit; transform: rotate(45deg); }}
  .kname {{ font-size: 10px; letter-spacing: 2px; color: {DIM}; }}
  .khead {{ font-size: 15px; margin: 4px 0; color: {TEXT}; line-height: 1.5; }}
  .kdetail {{ font-size: 12px; color: {DIM}; line-height: 1.6; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(310px, 1fr));
    gap: 14px; margin-bottom: 14px; }}
  .card {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px;
    padding: 14px 16px; box-shadow: 0 8px 22px rgba(0,0,0,0.35); }}
  .cardtop {{ display: flex; gap: 12px; align-items: center; margin-bottom: 8px; }}
  .cardtop .monster {{ width: 84px; min-width: 84px; }}
  .belief {{ color: {TEXT}; font-size: 12px; margin: 4px 0 2px; }}
  .rule {{ color: {DIM}; font-size: 11px; }}
  .statrow {{ display: flex; gap: 14px; margin-top: 10px; padding-top: 9px;
    border-top: 1px solid {BORDER}; font-size: 13px; }}
  .docs summary {{ font-size: 11px; letter-spacing: 2px; color: {AMBER}; cursor: pointer; }}
  .docs p {{ font-size: 12px; color: {TEXT}; margin: 10px 0 0; line-height: 1.7; max-width: 85ch; }}
  .docs b {{ color: {CYAN}; }} .docs i {{ color: {AMBER}; font-style: normal; }}
  footer {{ color: {DIM}; font-size: 10px; letter-spacing: 1px; margin-top: 18px; text-align: center; }}
</style></head><body>
<header><h1>⬢ THE SWARM <b>// MISSION CONTROL</b></h1></header>
{houston}
{leaderboard}
{docs}
{swarm_chart}
{monster_grid}
{market}
{rsi_chart}
{table("DECISION LOG", "one row per monster per day — 'no-change' is normal and good",
       ["DATE", "AGENT", "CLOSE", "WHAT IT SAW", "SIGNAL", "ACTION"], dec_rows, "no decisions yet")}
{table("TRADES", "rare by design — each one costs 0.35%",
       ["DATE", "AGENT", "SIDE", "QTY BTC", "PRICE", "COSTS", "EQUITY AFTER"], trade_rows,
       "no trades yet — everyone is waiting for their rule to trigger")}
{table("EVENTS", "notable moments: safety rails, launches, anything unusual",
       ["TIME", "KIND", "DETAIL"], event_rows, "no events")}
<footer>FOUR MONSTERS · ONE LAZY RIVAL · RULES LOCKED AT LAUNCH — HOUSTON WATCHES, HUMANS REVIEW WEEKLY · PAPER MONEY ONLY · NOT FINANCIAL ADVICE</footer>
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

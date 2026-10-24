"""Crypto mode across the pack: BTC-USD on UTC days, every day, 24 hours.

The bars here are SYNTHETIC (not market data), built in this file:
  day_chart()  Sat 2026-10-24 from 00:00 UTC: a 15-minute opening range of
               66,800 to 67,250, then the 00:20 bar closes at 67,380 (a breakout
               that closes at 00:25 UTC). A Saturday on purpose: crypto has no
               weekend.
  days_chart() 25 UTC days of 288 five-minute bars, a seeded random walk, with
               one missing bar (Yahoo skips a bar nobody traded in), then the
               first 6 bars of the plan's day.
"""

import datetime
import json
import os
import random
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
import io

from _load import load, ROOT

scan = load("trader-scanner", "scan")
entry = load("trader-entry", "entry")
exitp = load("trader-exit", "exit")
tm = load("trader-timemachine", "timemachine")
size = load("trader-budget", "size")
check = load("trader-risk", "check")
ticket = load("trader-broker", "ticket")
alerts = load("trader-alerts", "alerts")

DAY = "2026-10-24"
EPOCH = datetime.datetime(1970, 1, 1)
CRYPTO_CFG = {"budget": 5000, "cash_buffer_pct": 10, "max_position_pct": 75, "max_order_usd": 4000,
              "min_order_usd": 5, "max_loss_per_trade_usd": 50, "max_daily_loss_usd": 150, "max_trades_per_day": 3,
              "max_orders_per_day": 10, "min_reward_risk": 1.0, "require_stop": True,
              "no_entries_before": "09:45", "no_entries_after": "15:30", "flat_by": "15:55", "paper": True,
              "allow_crypto": True,
              "crypto": {"no_entries_before": "00:20", "no_entries_after": "23:00", "flat_by": "23:55"}}


def ts(day, hh=0, mm=0):
    return int((datetime.datetime.combine(datetime.date.fromisoformat(day), datetime.time(hh, mm)) - EPOCH)
               .total_seconds())


def v8(t, o, h, l, c, v, sym="BTC-USD", **meta):
    m = dict({"symbol": sym, "dataGranularity": "5m", "regularMarketTime": t[-1] + 300}, **meta)
    return {"chart": {"result": [{"meta": m, "timestamp": t, "indicators": {"quote": [
        {"open": o, "high": h, "low": l, "close": c, "volume": v}]}}], "error": None}}


def day_chart():
    bars = [(67000, 67250, 66900, 67100, 900), (67100, 67200, 66800, 66950, 800),
            (66950, 67150, 66850, 67120, 700), (67120, 67240, 67000, 67200, 600),
            (67200, 67400, 67150, 67380, 1500), (67380, 67500, 67300, 67450, 1200)]
    t = [ts(DAY) + 300 * i for i in range(len(bars))]
    return v8(t, *[[b[i] for b in bars] for i in range(5)], regularMarketPrice=67450)


def days_chart(days=25, upto_bar=6, seed=7, gap=(3, 100)):
    rng = random.Random(seed)
    end = datetime.date.fromisoformat(DAY)
    p = 67000.0
    cols = [[] for _ in range(6)]
    for n in range(days, -1, -1):
        d = (end - datetime.timedelta(days=n)).isoformat()
        for i in range(288 if n else upto_bar):
            if (days - n, i) == gap:
                continue
            op, cl = p, p * (1 + rng.gauss(0, 0.0015))
            row = (ts(d) + 300 * i, round(op, 2), round(max(op, cl) * (1 + abs(rng.gauss(0, 0.0007))), 2),
                   round(min(op, cl) * (1 - abs(rng.gauss(0, 0.0007))), 2), round(cl, 2), rng.randint(100, 2000))
            for col, x in zip(cols, row):
                col.append(x)
            p = cl
    return v8(*cols)


def run(fn, argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = fn(argv)
    return code, out.getvalue(), err.getvalue()


class Workspace(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.p = lambda *x: os.path.join(self.dir, *x)
        os.makedirs(self.p("trader"))
        with open(self.p("BTC-USD.json"), "w") as fh:
            json.dump(day_chart(), fh)
        with open(self.p("BTC-USD-60d5m.json"), "w") as fh:
            json.dump(days_chart(), fh)
        with open(self.p("trader", "config.json"), "w") as fh:
            json.dump(CRYPTO_CFG, fh)

    def tearDown(self):
        shutil.rmtree(self.dir)
        for m in (scan, entry, exitp, tm, size):
            m.use_market(False)

    def write(self, name, doc):
        with open(self.p(*name.split("/")), "w") as fh:
            json.dump(doc, fh)
        return self.p(*name.split("/"))

    def read(self, name):
        with open(self.p(*name.split("/"))) as fh:
            return json.load(fh)


class Detect(unittest.TestCase):
    def test_pairs_are_crypto_and_tickers_are_not(self):
        for m in (scan, entry, exitp, tm, size, check, ticket, alerts):
            self.assertTrue(m.is_crypto("BTC-USD"), m.__name__)
            self.assertTrue(m.is_crypto("eth-usd"), m.__name__)
            self.assertFalse(m.is_crypto("BTC"), m.__name__)       # an ETF on NYSE Arca, not the coin
            self.assertFalse(m.is_crypto("BRK.B"), m.__name__)
            self.assertFalse(m.is_crypto("BRK-B"), m.__name__)

    def test_crypto_time_is_utc_every_day(self):
        try:
            entry.use_market(True)
            sat = datetime.date(2026, 10, 24)
            self.assertEqual(entry.trading_day(sat), (True, ""))
            self.assertEqual(entry.session(sat), (datetime.time(0, 0), datetime.time(23, 59, 59)))
            utc = datetime.datetime(2026, 10, 24, 0, 30)
            self.assertEqual(entry.to_eastern(utc), utc)
            self.assertEqual(entry.parse_now("2026-10-24 00:30"), utc)
        finally:
            entry.use_market(False)
        self.assertEqual(entry.trading_day(datetime.date(2026, 10, 24)), (False, "weekend"))
        self.assertEqual(entry.parse_now("2026-10-24 00:30"), datetime.datetime(2026, 10, 24, 4, 30))


class Scanner(Workspace):
    def test_orb_on_a_saturday_at_midnight_utc(self):
        code, out, _ = run(scan.main, ["orb", "--offline", self.p("BTC-USD.json"), "--now", "2026-10-24 00:30",
                                       "--out", self.p("trader", "watchlist.json")])
        self.assertEqual(code, 0, out)
        self.assertIn("(crypto), Sat 2026-10-24 00:30 UTC: 15-minute range (00:00 to 00:15)", out)
        w = self.read("trader/watchlist.json")
        self.assertEqual(w["market"], "crypto")
        self.assertEqual(w["as_of"], "2026-10-24 00:30 UTC")
        h = w["hits"][0]
        self.assertEqual((h["symbol"], h["at"], h["price"], h["or_high"], h["or_low"]),
                         ("BTC-USD", "00:25", 67380.0, 67250.0, 66800.0))

    def test_the_range_is_still_forming_at_0012(self):
        code, _, err = run(scan.main, ["orb", "--offline", self.p("BTC-USD.json"), "--now", "2026-10-24 00:12",
                                       "--no-write"])
        self.assertEqual(code, 1)
        self.assertIn("It is 00:12 UTC: the 15-minute opening range runs 00:00 to 00:15", err)

    def test_stocks_and_crypto_never_mix(self):
        code, _, err = run(scan.main, ["daily", "--symbols", "BTC-USD,TSLA", "--no-write"])
        self.assertEqual(code, 1)
        self.assertIn("BTC-USD is a crypto pair", err)
        code, _, err = run(scan.main, ["daily", "--crypto", "--symbols", "TSLA", "--no-write"])
        self.assertIn("crypto mode scans crypto pairs only", err)

    def test_crypto_without_symbols_scans_the_main_pairs(self):
        scan.use_market(True)
        a = type("A", (), {"symbols": None, "watchlist": None, "universe": None, "limit": None})()
        self.assertEqual(scan.read_symbols(a)[:2], ["BTC-USD", "ETH-USD"])

    def test_offline_files_keep_the_pair_dash(self):
        data, _ = scan.load_offline(self.p("BTC-USD.json"))
        self.assertEqual(list(data), ["BTC-USD"])
        self.assertEqual(scan.from_yahoo("BRK-B"), "BRK.B")

    def test_the_window_comes_from_the_crypto_section(self):
        scan.use_market(True)
        cfg = scan.read_config(self.p("trader", "config.json"))
        self.assertEqual(cfg["no_entries_after"], "23:00")
        code, _, err = run(scan.main, ["orb", "--offline", self.p("BTC-USD.json"), "--now", "2026-10-24 23:30",
                                       "--config", self.p("trader", "config.json"), "--no-write"])
        self.assertEqual(code, 1)
        self.assertIn("after 23:00, your last time for new entries", err)


class Chain(Workspace):
    """scanner -> entry -> exit -> timemachine -> budget -> risk -> broker -> alerts, on BTC-USD."""

    def entry_json(self):
        code, out, err = run(entry.main, ["check", "BTC-USD", "--offline", self.p("BTC-USD.json"), "--now",
                                          "2026-10-24 00:30", "--config", self.p("trader", "config.json"),
                                          "--write", self.p("trader", "entry.json")])
        self.assertEqual(code, 0, out + err)
        return out

    def plan_json(self):
        self.entry_json()
        code, out, err = run(exitp.main, ["plan", "--from", self.p("trader", "entry.json"), "--now",
                                          "2026-10-24 00:30", "--config", self.p("trader", "config.json"),
                                          "--write", self.p("trader", "plan.json")])
        self.assertEqual(code, 0, out + err)
        return out

    def orders_json(self):
        self.plan_json()
        code, out, err = run(size.main, ["--plan", self.p("trader", "plan.json"), "--config",
                                         self.p("trader", "config.json"), "--portfolio", self.p("none.json"),
                                         "--prices", self.write("p.json", {}),
                                         "--now", "2026-10-24 00:30", "--write", self.p("trader", "orders.json")])
        self.assertEqual(code, 0, out + err)
        return out

    def test_entry_triggers_at_0025_utc(self):
        out = self.entry_json()
        self.assertIn("BTC-USD  Sat 2026-10-24 00:30 UTC", out)
        self.assertIn("TRIGGERED 00:25 at $67380.00", out)
        e = self.read("trader/entry.json")
        self.assertEqual((e["market"], e["status"], e["time"], e["price"], e["bar_index"]),
                         ("crypto", "triggered", "00:25", 67380.0, 4))

    def test_exit_plan_or_mid_2r_flat_by_2355_utc(self):
        out = self.plan_json()
        self.assertIn("Flat by       23:55 UTC", out)
        self.assertIn("Risk a coin   $355.00", out)
        self.assertNotIn("not today", out)
        p = self.read("trader/plan.json")
        self.assertEqual((p["market"], p["stop"], p["target"], p["risk_per_share"], p["flat_by"], p["entry_time"]),
                         ("crypto", 67025.0, 68090.0, 355.0, "23:55", "00:25"))

    def test_budget_sizes_in_millionths_of_a_coin(self):
        out = self.orders_json()
        self.assertIn("0.055654 BTC  <- binds", out)
        o = self.read("trader/orders.json")["orders"][0]
        self.assertEqual({k: o[k] for k in ("symbol", "side", "qty", "type", "time_in_force", "asset_class")},
                         {"symbol": "BTC-USD", "side": "buy", "qty": "0.055654", "type": "market",
                          "time_in_force": "gtc", "asset_class": "crypto"})
        self.assertNotIn("order_class", o)                 # Alpaca has no crypto brackets
        self.assertEqual(o["plan"]["max_loss"], 19.76)    # 0.055654 x 355.00
        self.assertEqual(o["plan"]["stop_limit_price"], 66689.88)

    def test_the_max_loss_binds_on_a_wide_stop(self):
        size.use_market(True)
        plan = {"symbol": "BTC-USD", "side": "buy", "entry": 67380, "stop": 65000, "target": 72140}
        s = size.size_trade(plan, dict(CRYPTO_CFG, max_position_pct=100, max_order_usd=10000))
        self.assertEqual((s["qty"], s["bound_by"]), (0.021008, "max loss"))   # 50 / 2380, rounded down
        self.assertLessEqual(s["max_loss"], 50)

    def risk(self, cfg=None, now="2026-10-24 00:30"):
        c = self.write("cfg.json", cfg or CRYPTO_CFG)
        return run(check.main, ["--orders", self.p("trader", "orders.json"), "--config", c, "--portfolio",
                                self.p("none.json"), "--prices", self.p("none.json"), "--state",
                                self.p("trader", "state", "broker.json"), "--out",
                                self.p("trader", "state", "risk.json"), "--now", now])

    def test_risk_blocks_crypto_unless_allowed(self):
        self.orders_json()
        code, out, _ = self.risk(dict(CRYPTO_CFG, allow_crypto=False))
        self.assertEqual(code, 1)
        self.assertIn("asset: BTC-USD is crypto; crypto is off", out)
        code, out, _ = self.risk()
        self.assertEqual(code, 0, out)
        self.assertIn("PASS  #1 buy BTC-USD 0.055654 BTC, entry", out)
        self.assertIn("ticket.py protect", out)

    def test_risk_reads_the_utc_window_for_crypto(self):
        self.orders_json()
        code, out, _ = self.risk(now="2026-10-24 23:30")      # all-crypto orders: --now is UTC
        self.assertEqual(code, 1)
        self.assertIn("window: no new crypto entries after 23:00 UTC (it is 23:30 UTC)", out)
        code, out, _ = self.risk(now="2026-10-24 00:10")
        self.assertIn("no new crypto entries before 00:20 UTC", out)

    def test_risk_blocks_a_crypto_bracket_and_a_day_order(self):
        res = check.check([{"symbol": "BTC-USD", "side": "buy", "qty": "0.01", "type": "market",
                            "time_in_force": "day", "order_class": "bracket", "take_profit_limit_price": "68090.00",
                            "stop_loss_stop_price": "67025.00", "plan": {"entry": 67380}}],
                          CRYPTO_CFG, now=datetime.datetime(2026, 10, 24, 0, 30))
        why = " ".join(res["results"][0]["reasons"])
        self.assertIn("no bracket or OCO orders for crypto", why)
        self.assertIn("crypto takes gtc or ioc", why)
        self.assertNotIn("whole shares", why)

    def test_broker_ticket_goes_to_place_crypto_order(self):
        self.orders_json()
        self.risk()
        common = ["--orders", self.p("trader", "orders.json"), "--config", self.p("trader", "config.json"),
                  "--risk", self.p("trader", "state", "risk.json"), "--state", self.p("trader", "state", "broker.json"),
                  "--now", "2026-10-24T00:30Z"]
        code, out, _ = run(ticket.main, ["show", "--index", "1", "--json"] + common)
        t = json.loads(out)
        self.assertTrue(t["ready"], t["status"])
        self.assertEqual(t["tool"], "place_crypto_order")
        self.assertEqual(t["tool_input"], {"symbol": "BTC/USD", "side": "buy", "order_type": "market",
                                           "time_in_force": "gtc", "qty": "0.055654"})
        self.assertEqual(t["max_loss"], 19.76)
        code, out, _ = run(ticket.main, ["approve", "--index", "1", "--reply", "yes"] + common)
        self.assertEqual(code, 0, out)
        code, out, _ = run(ticket.main, ["result", "--index", "1", "--status", "placed", "--filled-qty", "0.055654",
                                         "--filled-price", "67390", "--portfolio", self.p("trader", "portfolio.json")]
                           + common)
        self.assertIn("ticket.py protect --symbol BTC-USD", out)
        code, out, _ = run(ticket.main, ["protect", "--symbol", "BTC-USD", "--plan", self.p("trader", "plan.json"),
                                         "--portfolio", self.p("trader", "portfolio.json"), "--orders",
                                         self.p("trader", "orders.json"), "--config", self.p("trader", "config.json"),
                                         "--now", "2026-10-24T00:31Z"])
        self.assertEqual(code, 0, out)
        o = self.read("trader/orders.json")["orders"][0]
        self.assertEqual({k: o[k] for k in ("side", "qty", "type", "stop_price", "limit_price", "time_in_force")},
                         {"side": "sell", "qty": "0.055654", "type": "stop_limit", "stop_price": "67025.00",
                          "limit_price": "66689.88", "time_in_force": "gtc"})
        res = check.check([o], CRYPTO_CFG, portfolio=self.read("trader/portfolio.json"),
                          now=datetime.datetime(2026, 10, 24, 23, 59))   # an exit: never blocked by the window
        self.assertEqual((res["results"][0]["kind"], res["results"][0]["verdict"]), ("exit", "PASS"))

    def test_protect_refuses_a_stock_and_flatten_is_gtc_for_crypto(self):
        code, _, err = run(ticket.main, ["protect", "--symbol", "TSLA", "--qty", "8", "--stop", "358.32",
                                         "--orders", self.p("o.json")])
        self.assertEqual(code, 1)
        self.assertIn("protect is for crypto pairs", err)
        code, out, _ = run(ticket.main, ["flatten", "--symbol", "BTC-USD", "--qty", "0.055654", "--orders",
                                         self.p("o.json"), "--plan", self.p("none.json"), "--config",
                                         self.p("trader", "config.json"), "--now", "2026-10-24T23:55Z"])
        self.assertEqual(code, 0)
        o = self.read("o.json")["orders"][0]
        self.assertEqual((o["time_in_force"], o["type"]), ("gtc", "market"))
        self.assertIn("flat by 23:55 UTC", o["why"])

    def test_alerts_from_a_crypto_plan_ring_on_utc_time(self):
        self.plan_json()
        rules = alerts.rules_from_plan(self.read("trader/plan.json"))
        self.assertTrue(all(r["tz"] == "UTC" and r["date"] == DAY for r in rules))
        self.assertEqual(rules[-1]["at"], "23:55")
        status = alerts.market_status(datetime.datetime(2026, 10, 24, 23, 56))   # NYSE: a Saturday
        self.assertFalse(status["open"])
        q = {"BTC-USD": {"price": 66990.0}}
        rings, _ = alerts.evaluate(rules, q, status, {}, datetime.datetime(2026, 10, 24, 23, 56))
        ids = [r["id"] for r in rings]
        self.assertEqual(ids, ["btc-usd-plan-stop", "btc-usd-flat-by"])
        self.assertIn("BTC-USD is $66990.00", rings[0]["message"])
        rings, _ = alerts.evaluate(rules, q, status, {}, datetime.datetime(2026, 10, 25, 0, 5))
        self.assertEqual(rings, [])          # the plan's UTC day is over


class TimeMachine(Workspace):
    def plan(self, **kw):
        p = {"symbol": "BTC-USD", "side": "buy", "date": DAY, "entry": 79420.88, "stop": 79200.0,
             "target": 79900.0, "entry_time": "00:25", "setup": "orb", "opening_range": {"minutes": 15},
             "stop_rule": "pct", "interval": "5m"}
        p.update(kw)
        return p

    def run_tm(self, replays=500, **kw):
        tm.use_market(True)
        with open(self.p("BTC-USD-60d5m.json")) as fh:
            text = fh.read()
        return tm.time_machine(text, tm.normalize_plan(self.plan(**kw)), datetime.datetime(2026, 10, 24, 0, 30),
                               replays=replays, **{k: v for k, v in kw.items() if k == "until"})

    def test_a_crypto_day_is_288_bars_and_a_gap_is_filled(self):
        doc = self.run_tm()
        self.assertEqual(doc["market"], "crypto")
        self.assertEqual(doc["mc"]["pool_sessions"], 25)        # the day with one missing bar is kept
        self.assertEqual(doc["data"]["short_sessions_left_out"], [])
        self.assertEqual(doc["mc"]["bars_left"], 288 - 5)
        self.assertEqual(doc["mc"]["until"], "24:00")
        self.assertEqual(doc["plan"]["entry_bar"], 4)

    def test_same_seed_same_numbers(self):
        a, b = self.run_tm(), self.run_tm()
        self.assertEqual(a["mc"]["p_target"], b["mc"]["p_target"])
        self.assertAlmostEqual(a["mc"]["p_target"] + a["mc"]["p_stop"] + a["mc"]["p_neither"], 1.0, places=3)

    def test_a_long_gap_leaves_the_day_out(self):
        tm.use_market(True)
        s = {i: {"c": 1.0, "slot": i} for i in range(288) if not 100 <= i < 110}
        self.assertEqual(len(tm.fill_gaps(s)), 278)
        s = {i: {"c": 1.0, "slot": i} for i in range(288) if not 100 <= i < 103}
        self.assertEqual(len(tm.fill_gaps(s)), 288)

    def test_crypto_clock_reads_24_hours(self):
        tm.use_market(True)
        self.assertEqual(tm.parse_clock("01:25", "t"), 85)       # not 1:25 p.m.
        self.assertEqual(tm.clock12(85), "01:25")
        tm.use_market(False)
        self.assertEqual(tm.parse_clock("3:55", "t"), 15 * 60 + 55)

    def test_until_the_flat_by(self):
        doc = self.run_tm(until="23:55")
        self.assertEqual(doc["mc"]["until"], "23:55")
        self.assertEqual(doc["mc"]["bars_left"], 287 - 5)

    def test_the_chart_fits_on_a_screen(self):
        lines = tm.render_chart(self.run_tm())
        self.assertLessEqual(max(len(l) for l in lines), 130)


class StocksUntouched(unittest.TestCase):
    def test_stock_mode_is_the_default_everywhere(self):
        for m in (scan, entry, exitp, tm, size):
            self.assertFalse(m.MARKET["crypto"], m.__name__)
        self.assertEqual(tm.SESSION_BARS, 78)
        self.assertEqual(entry.OPEN, datetime.time(9, 30))


if __name__ == "__main__":
    unittest.main()

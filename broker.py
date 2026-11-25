"""Execution layer. One interface, three modes (config "broker"):

  sim     - built-in simulator (no account needed). Fills limit/stop orders from live prices.
  alpaca  - Alpaca Trading API. ALPACA_PAPER=true (default) uses the paper account; set it to
            false only when you're ready for real money.

Everything the bot does to money goes through here, so the Execution Trader's rules live here:
prices rounded to the penny, fractional quantities to 6 decimals, day orders re-placed each morning,
a unique client_order_id on every order (so a retry can never double-buy).
"""
import os, time, uuid, json, datetime as dt


def penny(x):
    return round(float(x) + 1e-9, 2)


def qty6(x):
    return float(f"{float(x):.6f}")


def cid(tag):
    return f"desk-{tag}-{uuid.uuid4().hex[:10]}"


class SimBroker:
    """Paper simulator: keeps its own cash/positions/orders in state['sim']."""
    name = "sim"

    def __init__(self, state, cash):
        self.s = state.setdefault("sim", {"cash": cash, "positions": {}, "orders": [], "fills": []})

    # account
    def account(self):
        return {"cash": self.s["cash"], "status": "SIM"}

    def positions(self):
        return {t: {"qty": p["qty"], "avg": p["avg"]} for t, p in self.s["positions"].items() if p["qty"] > 1e-9}

    def open_orders(self):
        return [o for o in self.s["orders"] if o["status"] == "open"]

    # orders
    def _add(self, **o):
        o.update(id=o.get("client_id") or cid(o["kind"]), status="open", created=time.time())
        self.s["orders"].append(o)
        del self.s["orders"][:-300]
        return o

    def limit_buy(self, t, qty, limit, tag="buy"):
        cost = qty * limit
        reserved = sum(o["qty"] * o["price"] for o in self.open_orders() if o["side"] == "buy")
        if cost > self.s["cash"] - reserved + 0.01:
            raise ValueError("insufficient buying power")
        return self._add(symbol=t, side="buy", kind="limit", qty=qty6(qty), price=penny(limit), client_id=cid(tag))

    def market_buy(self, t, notional, price_now, tag="buy"):
        qty = qty6(notional / price_now)
        return self._fill(self._add(symbol=t, side="buy", kind="market", qty=qty, price=penny(price_now), client_id=cid(tag)), price_now)

    def stop_sell(self, t, qty, stop, tag="stop"):
        return self._add(symbol=t, side="sell", kind="stop", qty=qty6(qty), price=penny(stop), client_id=cid(tag))

    def limit_sell(self, t, qty, limit, tag="tp"):
        return self._add(symbol=t, side="sell", kind="limit", qty=qty6(qty), price=penny(limit), client_id=cid(tag))

    def market_sell(self, t, qty, price_now, tag="exit"):
        return self._fill(self._add(symbol=t, side="sell", kind="market", qty=qty6(qty), price=penny(price_now), client_id=cid(tag)), price_now)

    def limit_buy_ext(self, t, qty, limit, tag="au", price_now=None):
        """Extended-hours limit buy (simulated: fills at once if the current price is at or under the limit)."""
        o = self.limit_buy(t, qty, limit, tag)
        if price_now is not None and float(price_now) <= float(limit):
            o["instant"] = True
            return self._fill(o, price_now)
        return o

    def limit_sell_ext(self, t, qty, limit, tag="aux", price_now=None):
        """Extended-hours limit sell (simulated: fills at once if the current price is at or above the limit)."""
        o = self.limit_sell(t, qty, limit, tag)
        if price_now is not None and float(price_now) >= float(limit):
            o["instant"] = True
            return self._fill(o, price_now)
        return o

    def cancel(self, oid):
        for o in self.s["orders"]:
            if o["id"] == oid and o["status"] == "open":
                o["status"] = "canceled"

    def cancel_all(self, symbol=None):
        for o in self.open_orders():
            if symbol is None or o["symbol"] == symbol:
                o["status"] = "canceled"

    def expire_day_orders(self):
        for o in self.open_orders():
            o["status"] = "expired"

    def _fill(self, o, px):
        px = float(px)
        p = self.s["positions"].setdefault(o["symbol"], {"qty": 0.0, "avg": 0.0})
        if o["side"] == "buy":
            cost = o["qty"] * px
            p["avg"] = (p["avg"] * p["qty"] + cost) / (p["qty"] + o["qty"])
            p["qty"] = qty6(p["qty"] + o["qty"])
            self.s["cash"] -= cost
        else:
            q = min(o["qty"], p["qty"])
            p["qty"] = qty6(p["qty"] - q)
            self.s["cash"] += q * px
            o["qty"] = q
        o.update(status="filled", fill_price=penny(px), filled_at=dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
        self.s["fills"].append({k: o[k] for k in ("id", "symbol", "side", "kind", "qty", "fill_price", "filled_at", "client_id")})
        del self.s["fills"][:-500]
        if o["kind"] == "market" or o.get("instant"):
            self.s.setdefault("unsynced", []).append(o)  # reported on the next sync() (instant fills, incl. simulated after-hours buys)
        return o

    def sync(self, intraday):
        """Check resting orders against 5-min bars printed AFTER each order was placed; return new fills."""
        import pandas as pd
        new = self.s.pop("unsynced", [])
        self.s["unsynced"] = []
        for o in self.open_orders():
            df = intraday.get(o["symbol"])
            if df is None or df.empty:
                continue
            b = df[df.index >= pd.Timestamp(o["created"], unit="s", tz="UTC").tz_convert(df.index.tz)]
            if b.empty:
                continue
            low, high, last = float(b.Low.min()), float(b.High.max()), float(b.Close.iloc[-1])
            if o["side"] == "buy" and o["kind"] == "limit" and low <= o["price"]:
                new.append(self._fill(o, min(o["price"], last) if last < o["price"] else o["price"]))
            elif o["side"] == "sell" and o["kind"] == "stop" and low <= o["price"]:
                new.append(self._fill(o, min(o["price"], last)))
            elif o["side"] == "sell" and o["kind"] == "limit" and high >= o["price"]:
                new.append(self._fill(o, max(o["price"], last) if last > o["price"] else o["price"]))
        return new


class AlpacaBroker:
    """Alpaca Trading API (alpaca-py). Fractional orders must be time_in_force=DAY."""
    name = "alpaca"

    def __init__(self, state):
        from alpaca.trading.client import TradingClient
        self.paper = os.environ.get("ALPACA_PAPER", "true").lower() != "false"
        self.c = TradingClient(os.environ["ALPACA_KEY"], os.environ["ALPACA_SECRET"], paper=self.paper)
        self.name = "alpaca-paper" if self.paper else "alpaca-LIVE"
        self.state = state
        self.seen = set(state.setdefault("alpaca_seen_fills", []))

    def _req(self, cls, **kw):
        from alpaca.trading.enums import OrderSide, TimeInForce
        kw["side"] = OrderSide.BUY if kw["side"] == "buy" else OrderSide.SELL
        kw["time_in_force"] = TimeInForce.DAY
        return self.c.submit_order(cls(**kw))

    def limit_sell_ext(self, t, qty, limit, tag="aux", price_now=None):
        """Extended-hours (4-8 PM) limit sell."""
        from alpaca.trading.requests import LimitOrderRequest
        return self._o(self._req(LimitOrderRequest, symbol=t, qty=qty6(qty), side="sell", limit_price=penny(limit),
                                 extended_hours=True, client_order_id=cid(tag)))

    def limit_buy_ext(self, t, qty, limit, tag="au", price_now=None):
        """Extended-hours (4-8 PM) limit buy; fractional shares need the asset's fractional_eh_enabled flag."""
        from alpaca.trading.requests import LimitOrderRequest
        return self._o(self._req(LimitOrderRequest, symbol=t, qty=qty6(qty), side="buy", limit_price=penny(limit),
                                 extended_hours=True, client_order_id=cid(tag)))

    @staticmethod
    def _o(o):
        return {"id": str(o.id), "symbol": o.symbol, "side": o.side.value, "kind": o.order_type.value,
                "qty": float(o.qty or 0), "price": float(o.limit_price or o.stop_price or 0),
                "status": o.status.value, "client_id": o.client_order_id}

    def account(self):
        a = self.c.get_account()
        return {"cash": float(a.cash), "equity": float(a.equity), "buying_power": float(a.buying_power),
                "status": str(a.status), "blocked": bool(a.trading_blocked)}

    def positions(self):
        return {p.symbol: {"qty": float(p.qty), "avg": float(p.avg_entry_price)} for p in self.c.get_all_positions()}

    def open_orders(self):
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        return [self._o(o) for o in self.c.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=100))]

    def limit_buy(self, t, qty, limit, tag="buy"):
        from alpaca.trading.requests import LimitOrderRequest
        return self._o(self._req(LimitOrderRequest, symbol=t, qty=qty6(qty), side="buy", limit_price=penny(limit), client_order_id=cid(tag)))

    def market_buy(self, t, notional, price_now, tag="buy"):
        from alpaca.trading.requests import MarketOrderRequest
        return self._o(self._req(MarketOrderRequest, symbol=t, notional=penny(notional), side="buy", client_order_id=cid(tag)))

    def stop_sell(self, t, qty, stop, tag="stop"):
        from alpaca.trading.requests import StopOrderRequest
        return self._o(self._req(StopOrderRequest, symbol=t, qty=qty6(qty), side="sell", stop_price=penny(stop), client_order_id=cid(tag)))

    def limit_sell(self, t, qty, limit, tag="tp"):
        from alpaca.trading.requests import LimitOrderRequest
        return self._o(self._req(LimitOrderRequest, symbol=t, qty=qty6(qty), side="sell", limit_price=penny(limit), client_order_id=cid(tag)))

    def market_sell(self, t, qty, price_now, tag="exit"):
        from alpaca.trading.requests import MarketOrderRequest
        return self._o(self._req(MarketOrderRequest, symbol=t, qty=qty6(qty), side="sell", client_order_id=cid(tag)))

    def cancel(self, oid):
        try:
            self.c.cancel_order_by_id(oid)
        except Exception as e:
            print("cancel failed", oid, e)

    def cancel_all(self, symbol=None):
        for o in self.open_orders():
            if symbol is None or o["symbol"] == symbol:
                self.cancel(o["id"])

    def expire_day_orders(self):
        pass  # Alpaca expires DAY orders itself

    def sync(self, bars=None):
        """Return fills not seen before (from closed orders of the last 3 days)."""
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        after = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)
        new = []
        for o in self.c.get_orders(GetOrdersRequest(status=QueryOrderStatus.CLOSED, after=after, limit=200)):
            if o.filled_at and str(o.id) not in self.seen and float(o.filled_qty or 0) > 0:
                self.seen.add(str(o.id))
                d = self._o(o)
                d.update(qty=float(o.filled_qty), fill_price=float(o.filled_avg_price),
                         filled_at=o.filled_at.astimezone().strftime("%Y-%m-%d %H:%M"), status="filled")
                new.append(d)
        self.state["alpaca_seen_fills"] = list(self.seen)[-1000:]
        return new


def make(cfg, state):
    if cfg.get("broker") == "alpaca" and os.environ.get("ALPACA_KEY"):
        return AlpacaBroker(state)
    return SimBroker(state, cfg["starting_cash"])

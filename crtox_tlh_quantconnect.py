from AlgorithmImports import *
from datetime import timedelta

class CrtoxMomentumTLH(QCAlgorithm):
    """
    CRTOX-style Momentum Rotation with Tax-Loss Harvesting
    ========================================================
    - Monthly dual-momentum rotation across thematic ETFs
    - Composite momentum score: 50% 6M + 25% 1M + 12.5% 3M + 12.5% 12M
    - Absolute momentum filter vs SGOV (risk-free proxy)
    - Hold top 7 by relative momentum that pass absolute filter
    - Risk-off: SGOV (current CRTOX approach)
    - TLH: When any holding has >5% unrealized loss and there's a swap
      pair available, harvest the loss and buy the substitute
    - 30-day wash sale tracking per ticker
    """

    # CRTOX equity universe
    UNIVERSE = [
        "SMH", "IBB", "SIL", "SILJ", "XME", "ITA", "XAR",
        "IWO", "ILF", "EFV", "SOXX", "IGV", "IAI",
    ]

    # TLH swap pairs (substantially non-identical, same exposure)
    TLH_PAIRS = {
        "SMH": "SOXX", "SOXX": "SMH",
        "IBB": "XBI",  "XBI": "IBB",
        "SIL": "SILJ", "SILJ": "SIL",
        "XME": "PICK",
        "ITA": "XAR",  "XAR": "ITA",
        "IWO": "VBK",
        "ILF": "EWZ",
        "EFV": "FNDF",
        "IGV": "FTEC",
        "IAI": "KCE",
        "SGOV": "BIL",
    }

    RISK_OFF = "SGOV"
    N_HOLD = 7
    REBAL_DAYS = 21
    TLH_LOSS_THRESHOLD = -0.05
    WASH_SALE_DAYS = 31

    def initialize(self):
        self.set_start_date(2021, 1, 1)
        self.set_end_date(2026, 2, 1)
        self.set_cash(1_000_000)
        self.set_benchmark("SPY")

        self.universe_settings.resolution = Resolution.DAILY

        all_tickers = set(self.UNIVERSE)
        all_tickers.add(self.RISK_OFF)
        all_tickers.add("SPY")
        for v in self.TLH_PAIRS.values():
            all_tickers.add(v)

        self.symbols = {}
        for t in all_tickers:
            try:
                sym = self.add_equity(t, Resolution.DAILY).symbol
                self.symbols[t] = sym
            except:
                self.debug(f"Could not add {t}")

        # TLH tracking
        self.wash_sale_dates = {}
        self.total_harvested = 0.0
        self.harvest_count = 0
        self.current_holdings_tickers = []

        self.schedule.on(
            self.date_rules.month_start("SPY"),
            self.time_rules.after_market_open("SPY", 30),
            self.rebalance
        )

        self.schedule.on(
            self.date_rules.every_day("SPY"),
            self.time_rules.after_market_open("SPY", 60),
            self.check_tlh
        )

        self.set_warm_up(timedelta(days=365))

    def momentum_score(self, ticker):
        if ticker not in self.symbols:
            return None
        sym = self.symbols[ticker]
        lookbacks = {21: 0.25, 63: 0.125, 126: 0.50, 252: 0.125}
        total = 0.0
        for lb, wt in lookbacks.items():
            hist = self.history(sym, lb + 1, Resolution.DAILY)
            if hist.empty or len(hist) < lb:
                return None
            try:
                prices = hist["close"]
                if len(prices) < 2:
                    return None
                ret = prices.iloc[-1] / prices.iloc[0] - 1.0
                total += ret * wt
            except:
                return None
        return total

    def absolute_momentum_pass(self, ticker):
        score_asset = self.momentum_score(ticker)
        score_rf = self.momentum_score(self.RISK_OFF)
        if score_asset is None:
            return False
        if score_rf is None:
            return True
        return score_asset > score_rf

    def rebalance(self):
        if self.is_warming_up:
            return

        scores = {}
        for t in self.UNIVERSE:
            s = self.momentum_score(t)
            if s is not None:
                scores[t] = s

        ranked = sorted(scores.items(), key=lambda x: -x[1])

        selected = []
        for t, s in ranked:
            if len(selected) >= self.N_HOLD:
                break
            if self.absolute_momentum_pass(t):
                selected.append(t)

        if len(selected) < self.N_HOLD:
            for t, s in ranked:
                if t not in selected and len(selected) < self.N_HOLD:
                    selected.append(t)

        target_weight = 1.0 / max(len(selected), 1)

        current_tickers = set()
        for kvp in self.portfolio:
            if kvp.value.invested and kvp.key.value in [self.symbols.get(t) for t in self.UNIVERSE + list(self.TLH_PAIRS.values()) if t in self.symbols]:
                ticker_name = None
                for name, sym in self.symbols.items():
                    if sym == kvp.key:
                        ticker_name = name
                        break
                if ticker_name:
                    current_tickers.add(ticker_name)

        to_sell = []
        for t in current_tickers:
            canonical = t
            for primary, sub in self.TLH_PAIRS.items():
                if sub == t and primary in self.UNIVERSE:
                    canonical = primary
                    break
            if canonical not in selected:
                to_sell.append(t)

        for t in to_sell:
            if t in self.symbols:
                holding = self.portfolio[self.symbols[t]]
                if holding.invested and holding.unrealized_profit < 0:
                    loss = holding.unrealized_profit
                    self.total_harvested += abs(loss)
                    self.harvest_count += 1
                    self.debug(f"TLH HARVEST (rotation): {t} loss=${loss:,.2f}")
                self.liquidate(self.symbols[t])

        for t in selected:
            actual_ticker = t
            if t in self.wash_sale_dates:
                wash_end = self.wash_sale_dates[t]
                if self.time < wash_end and t in self.TLH_PAIRS:
                    actual_ticker = self.TLH_PAIRS[t]

            if actual_ticker in self.symbols:
                self.set_holdings(self.symbols[actual_ticker], target_weight)

        risk_off_needed = max(0, self.N_HOLD - len(selected))
        if risk_off_needed > 0 or len(selected) == 0:
            rf_weight = 1.0 - target_weight * len(selected)
            if rf_weight > 0.01 and self.RISK_OFF in self.symbols:
                self.set_holdings(self.symbols[self.RISK_OFF], rf_weight)

        self.current_holdings_tickers = selected
        self.debug(f"REBAL: {selected} | Scores: {[(t, f'{scores.get(t,0):.3f}') for t in selected[:3]]}")

    def check_tlh(self):
        if self.is_warming_up:
            return

        for kvp in self.portfolio:
            if not kvp.value.invested:
                continue
            holding = kvp.value
            sym = kvp.key

            ticker_name = None
            for name, s in self.symbols.items():
                if s == sym:
                    ticker_name = name
                    break
            if not ticker_name:
                continue

            if ticker_name == self.RISK_OFF:
                continue

            cost = holding.average_price
            current = holding.price
            if cost <= 0 or current <= 0:
                continue

            unrealized_pct = (current / cost) - 1.0

            if unrealized_pct < self.TLH_LOSS_THRESHOLD:
                primary = ticker_name
                for p, sub in self.TLH_PAIRS.items():
                    if sub == ticker_name:
                        primary = p
                        break

                substitute = self.TLH_PAIRS.get(primary) or self.TLH_PAIRS.get(ticker_name)
                if not substitute or substitute not in self.symbols:
                    continue

                if substitute in self.wash_sale_dates:
                    if self.time < self.wash_sale_dates[substitute]:
                        continue

                qty = holding.quantity
                loss = holding.unrealized_profit
                self.total_harvested += abs(loss)
                self.harvest_count += 1

                self.liquidate(sym)
                target_value = qty * current
                sub_price = self.securities[self.symbols[substitute]].price
                if sub_price > 0:
                    sub_qty = int(target_value / sub_price)
                    if sub_qty > 0:
                        self.market_order(self.symbols[substitute], sub_qty)

                self.wash_sale_dates[ticker_name] = self.time + timedelta(days=self.WASH_SALE_DAYS)

                self.debug(
                    f"TLH: {ticker_name} -> {substitute} | "
                    f"Loss=${loss:,.2f} ({unrealized_pct:.1%}) | "
                    f"Total harvested=${self.total_harvested:,.2f}"
                )

    def on_end_of_algorithm(self):
        self.debug(f"=== TLH SUMMARY ===")
        self.debug(f"Total losses harvested: ${self.total_harvested:,.2f}")
        self.debug(f"Number of harvest events: {self.harvest_count}")
        self.debug(f"Avg harvest size: ${self.total_harvested / max(self.harvest_count, 1):,.2f}")
        years = (self.end_date - self.start_date).days / 365.25
        self.debug(f"Annual harvested: ${self.total_harvested / years:,.2f}")
        self.debug(f"Harvested as % of starting capital: {self.total_harvested / 1_000_000 * 100:.2f}%")
        self.debug(f"Annual harvest rate: {self.total_harvested / years / 1_000_000 * 100:.2f}% of capital")

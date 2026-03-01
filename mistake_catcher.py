import time
from bot_template import BaseBot, OrderBook, OrderRequest, Side, Trade

class MistakeCatcher(BaseBot):
    def __init__(self, cmi_url: str, username: str, password: str):
        super().__init__(cmi_url, username, password)
        
        # Track the top of the book (Best Bid, Best Ask) for ETF arbitrage
        # ETF Spot Price settles exactly to Market 1 + 3 + 5 [cite: 623]
        self.market_state = {
            "TIDE_SPOT": {"bid": None, "ask": None},
            "WX_SPOT": {"bid": None, "ask": None},
            "LHR_COUNT": {"bid": None, "ask": None},
            "LON_ETF": {"bid": None, "ask": None}
        }
        
        self.last_execution_time = 0.0
        self.trade_volume_executed = 0

    def on_trades(self, trade: Trade) -> None:
        pass

    def on_orderbook(self, ob: OrderBook) -> None:
        if ob.product not in self.market_state:
            return

        best_bid = ob.buy_orders[0].price if ob.buy_orders else None
        best_ask = ob.sell_orders[0].price if ob.sell_orders else None

        self.market_state[ob.product] = {"bid": best_bid, "ask": best_ask}
        self.check_arbitrage()

    def check_arbitrage(self) -> None:
            # Prevent hitting the 1 request/sec rate limit
            if time.time() - self.last_execution_time < 1.5:
                return
                
            # Hard stop if approaching the +/- 100 position limit
            if self.trade_volume_executed >= 90:
                print("WARNING: Approaching position limits. Halting trading to avoid bans.")
                return

            # Safely pull the top-of-book prices AND volumes
            try:
                tide_ask, tide_bid = self.market_state["TIDE_SPOT"]["ask"], self.market_state["TIDE_SPOT"]["bid"]
                wx_ask, wx_bid = self.market_state["WX_SPOT"]["ask"], self.market_state["WX_SPOT"]["bid"]
                lhr_ask, lhr_bid = self.market_state["LHR_COUNT"]["ask"], self.market_state["LHR_COUNT"]["bid"]
                etf_ask, etf_bid = self.market_state["LON_ETF"]["ask"], self.market_state["LON_ETF"]["bid"]
            except KeyError:
                return # Skip if books aren't populated yet

            if None in (tide_ask, wx_ask, lhr_ask, etf_bid, tide_bid, wx_bid, lhr_bid, etf_ask):
                return

            # --- THE FIX: MARGIN OF SAFETY ---
            # Only trade if the guaranteed profit is greater than 50 ticks. 
            # This protects you against minor price slippage when your orders hit the book.
            PROFIT_MARGIN = 50 

            # SCENARIO A: ETF Bid is significantly higher than the sum of Component Asks
            synthetic_ask = tide_ask + wx_ask + lhr_ask
            if (etf_bid - synthetic_ask) > PROFIT_MARGIN:
                print(f"OPPORTUNITY A: Buy Components ({synthetic_ask}), Sell ETF ({etf_bid}) | Profit: {etf_bid - synthetic_ask}")
                self.execute_arbitrage_trade(
                    etf_side=Side.SELL, etf_price=etf_bid,
                    comp_side=Side.BUY, tide_p=tide_ask, wx_p=wx_ask, lhr_p=lhr_ask
                )
                return

            # SCENARIO B: ETF Ask is significantly lower than the sum of Component Bids
            synthetic_bid = tide_bid + wx_bid + lhr_bid
            if (synthetic_bid - etf_ask) > PROFIT_MARGIN:
                print(f"OPPORTUNITY B: Buy ETF ({etf_ask}), Sell Components ({synthetic_bid}) | Profit: {synthetic_bid - etf_ask}")
                self.execute_arbitrage_trade(
                    etf_side=Side.BUY, etf_price=etf_ask,
                    comp_side=Side.SELL, tide_p=tide_bid, wx_p=wx_bid, lhr_p=lhr_bid
                )
                return

    def execute_arbitrage_trade(self, etf_side: Side, etf_price: float, comp_side: Side, tide_p: float, wx_p: float, lhr_p: float):
        self.last_execution_time = time.time()
        self.trade_volume_executed += 1 
        
        orders = [
            OrderRequest("LON_ETF", etf_price, etf_side, 1),
            OrderRequest("TIDE_SPOT", tide_p, comp_side, 1),
            OrderRequest("WX_SPOT", wx_p, comp_side, 1),
            OrderRequest("LHR_COUNT", lhr_p, comp_side, 1)
        ]

        responses = self.send_orders(orders)
        print(f"Fired {len(responses)} legs of the arbitrage trade.")

        # Simulate IOC by canceling unfilled remnants 
        for resp in responses:
            if resp.volume > resp.filled:
                self.cancel_order(resp.id)

if __name__ == "__main__":
    # --- UPDATE YOUR CREDENTIALS HERE ---
    USERNAME = "45clubs"
    PASSWORD = "chudgoon"
    
    # Keeping it on TEST_URL for your first run. 
    # Swap to the production challenge URL once you confirm it works!
    TEST_URL = "http://ec2-52-49-69-152.eu-west-1.compute.amazonaws.com/"
    
    bot = MistakeCatcher(TEST_URL, USERNAME, PASSWORD)
    
    print(f"Starting Mistake Catcher for {USERNAME}...")
    bot.start()
    
    try:
        while True:
            time.sleep(1) 
    except KeyboardInterrupt:
        bot.cancel_all_orders()
        bot.stop()
        print("Bot stopped. All open orders cancelled.")
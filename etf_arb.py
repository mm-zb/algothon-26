import time
from bot_template import BaseBot, OrderBook, OrderRequest, Trade, Side

class ETFArbBot(BaseBot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.etf_ticker = 'LON_ETF'
        self.constituents = ['TIDE_SPOT', 'WX_SPOT', 'LHR_COUNT']
        
        # Track best prices from the SSE stream
        self.best_bids = {}
        self.best_asks = {}
        
        # Track positions to avoid the +/- 100 ban limit
        self.positions = {ticker: 0 for ticker in self.constituents + [self.etf_ticker]}
        
        # Rate limiting: don't trade more than once every 2 seconds to be safe
        self.last_trade_time = 0 
        self.cooldown_seconds = 2.0

    def on_trades(self, trade: Trade):
        # Update our position tracking when our own trades execute
        if trade.buyer == self.username:
            self.positions[trade.product] += trade.volume
        elif trade.seller == self.username:
            self.positions[trade.product] -= trade.volume
            
        print(f"Fill: {trade.volume}x {trade.product} @ {trade.price} | New Pos: {self.positions[trade.product]}")

    def on_orderbook(self, ob: OrderBook):
        # 1. Keep our internal price dictionary up to date
        if ob.buy_orders:
            # buy_orders are sorted highest price first
            self.best_bids[ob.product] = ob.buy_orders[0].price
        if ob.sell_orders:
            # sell_orders are sorted lowest price first
            self.best_asks[ob.product] = ob.sell_orders[0].price

        # 2. Check if we have enough data to calculate the arb
        required_tickers = self.constituents + [self.etf_ticker]
        if not all(t in self.best_bids and t in self.best_asks for t in required_tickers):
            return

        # 3. Rate limit check
        if time.time() - self.last_trade_time < self.cooldown_seconds:
            return

        # 4. Calculate Synthetic Prices
        # Cost to buy the synthetic ETF (lift the asks of all 3 parts)
        synthetic_ask = sum(self.best_asks[p] for p in self.constituents)
        # Revenue from selling the synthetic ETF (hit the bids of all 3 parts)
        synthetic_bid = sum(self.best_bids[p] for p in self.constituents)

        # 5. Hunt for Arbitrage!
        # Condition A: Real ETF is cheaper than the parts. Buy ETF, Sell Parts.
        if self.best_asks[self.etf_ticker] < synthetic_bid:
            self.execute_arbitrage(buy_etf=True)

        # Condition B: Real ETF is more expensive than parts. Sell ETF, Buy Parts.
        elif self.best_bids[self.etf_ticker] > synthetic_ask:
            self.execute_arbitrage(buy_etf=False)

    def execute_arbitrage(self, buy_etf: bool):
        # Safety Check: Strict position limits!
        trade_volume = 1
        if buy_etf and (self.positions[self.etf_ticker] + trade_volume > 100 or any(self.positions[p] - trade_volume < -100 for p in self.constituents)):
            return
        elif not buy_etf and (self.positions[self.etf_ticker] - trade_volume < -100 or any(self.positions[p] + trade_volume > 100 for p in self.constituents)):
            return

        orders_to_send = []
        
        if buy_etf:
            print(f"ARB FOUND! Buying ETF @ {self.best_asks[self.etf_ticker]} | Selling Parts @ {sum(self.best_bids[p] for p in self.constituents)}")
            orders_to_send.append(OrderRequest(self.etf_ticker, self.best_asks[self.etf_ticker], Side.BUY, trade_volume))
            for p in self.constituents:
                orders_to_send.append(OrderRequest(p, self.best_bids[p], Side.SELL, trade_volume))
        else:
            print(f"ARB FOUND! Selling ETF @ {self.best_bids[self.etf_ticker]} | Buying Parts @ {sum(self.best_asks[p] for p in self.constituents)}")
            orders_to_send.append(OrderRequest(self.etf_ticker, self.best_bids[self.etf_ticker], Side.SELL, trade_volume))
            for p in self.constituents:
                orders_to_send.append(OrderRequest(p, self.best_asks[p], Side.BUY, trade_volume))

        # Send all 4 orders simultaneously using the base class threaded helper
        self.send_orders(orders_to_send)
        self.last_trade_time = time.time()


if __name__ == "__main__":
    # Use the test exchange first as suggested in the notebook!
    EXCHANGE_URL = "http://ec2-52-49-69-152.eu-west-1.compute.amazonaws.com/" 
    USERNAME = "45clubs" # Replace with your team username
    PASSWORD = "chudgoon" # Replace with your team password
    
    bot = ETFArbBot(EXCHANGE_URL, USERNAME, PASSWORD)
    
    print("Syncing initial positions...")
    initial_positions = bot.get_positions()
    for product, pos in initial_positions.items():
        if product in bot.positions:
            bot.positions[product] = pos
            
    print("Starting ETF Arbitrage Bot...")
    try:
        bot.start()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping bot and cancelling all open orders...")
        bot.cancel_all_orders()
        bot.stop()
        print("Bot safely shut down.")
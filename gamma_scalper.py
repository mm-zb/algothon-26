import time
from bot_template import BaseBot, OrderBook, Trade, Side, OrderRequest
from constants import TEST_URL, COMP_URL, USERNAME, PASSWORD

# -- gamma scalp calculation helpers --

# calculates the delta of one LON_FLY contract
# dependent on the current price of the ETF
# < 6200        -> -2
# 6200-6600     -> +1
# 6600-7000     -> -1
# > 7000        -> +2
def get_lon_fly_delta(self, etf_price: float) -> float:
    if etf_price < 6200:
        return -2.0
    if 6200 <= etf_price < 6600:
        return 1.0
    if 6600 <= etf_price < 7000:
        return -1.0
    return 2.0

class GammaScalper(BaseBot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_fly_inventory
    
    # calculates net delta and trades the etf to offset it
    def rehedge(self):
        # TODO: use stream instead of big get
        # update manually
        positions = self.get_positions()
        fly_pos = positions.get("LON_FLY", 0)
        etf_pos = positions.get("LON_ETF", 0)
        
        # get current etf price
        ob_etf = self.get_orderbook("LON_ETF")

        # no positions
        if not (ob_etf.buy_orders and ob_etf.sell_orders):
            return
        etf_mid = (ob_etf.buy_orders[0].price + ob_etf.sell_orders[0].price) / 2
        
        # calculate how much etf we should have
        current_lon_fly_delta = get_lon_fly_delta(etf_mid)
        desired_etf_pos = round(-(fly_pos * current_lon_fly_delta))
        
        diff = desired_etf_pos - etf_pos
        
        if diff > 0:
            self.send_order(OrderRequest("LON_ETF", ob_etf.sell_orders[0].price, Side.BUY, abs(diff)))
            print(f"Hedged: Buying {diff} LON_ETF")
        elif diff < 0:
            self.send_order(OrderRequest("LON_ETF", ob_etf.buy_orders[0].price, Side.SELL, abs(diff)))
            print(f"Hedged: Selling {abs(diff)} LON_ETF")

        # -- callbacks --

        # these functions trigger on changes in the order book, and on every trade
        
        # overridden abstract method
        def on_orderbook(self, ob: OrderBook):
            # we only care about moves in the etf to trigger a hedge
            if ob.product == "LON_ETF":
                self.rehedge()

        # overridden abstract method
        def on_trades(self, trade: Trade):
            # if we get a fill on a LON_FLY, we need to hedge immediately
            if trade.product == "LON_FLY":
                self.rehedge()


if __name__ == "__main__":
    goon = GammaScalper(TEST_URL, USERNAME, PASSWORD, target_fly=5)
    
    print("Starting Gamma Scalper...")
    goon.start() # starts the live SSE stream for on_orderbook / on_trades

    try:
        while True:
            # main loop handles inventory acquisition and general status
            goon.manage_inventory()
            
            # print status every 10 seconds
            pos = goon.get_positions()
            print(f"Current Positions: {pos}")
            
            time.sleep(5) 

    except KeyboardInterrupt:
        print("Stopping bot...")
        goon.stop()
        print("Bot stopped.")
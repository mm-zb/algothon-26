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
    def __init__(self, cmi_url, username, password, target_fly=10):
        super().__init__(cmi_url, username, password)
        self.target_fly = target_fly
        self.last_hedge_time = 0
        self.cooldown = 1.1 # avoid getting rate limited
    
    # calculates net delta and trades the etf to offset it
    def rehedge(self):

        # avoid rate limit
        if time.time() - self.last_hedge_time < self.cooldown:
            return
        
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


        if abs(diff) >= 1:
            # only trade if we want more than 1 share
            self.last_hedge_time = time.time()
            if diff > 0:
                self.send_order(OrderRequest("LON_ETF", ob_etf.sell_orders[0].price, Side.BUY, abs(diff)))
                print(f"Hedged: Buying {diff} LON_ETF")
            elif diff < 0:
                self.send_order(OrderRequest("LON_ETF", ob_etf.buy_orders[0].price, Side.SELL, abs(diff)))
                print(f"Hedged: Selling {abs(diff)} LON_ETF")
        return

    def manage_inventory(self):
        # avoid getting rate limited
        if time.time() - self.last_hedge_time < self.cooldown:
            return
        
        # get positions
        positions = self.get_positions()
        current_fly = positions.get("LON_FLY", 0)

        # buy more LON_FLY if inventory is low
        if current_fly < self.target_fly:
            ob_fly = self.get_orderbook("LON_FLY")
            if ob_fly.sell_orders:
                buy_qty = self.target_fly - current_fly
                print(f"Inventory Low: Buying {buy_qty} LON_FLY")
                self.send_order(OrderRequest("LON_FLY", ob_fly.sell_orders[0].price, Side.BUY, int(buy_qty)))
                self.last_hedge_time = time.time()

        


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
            print(f"Trade filled on FLY: {trade.volume}@{trade.price}")
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
import time
import math
from bot_template import BaseBot, OrderBook, OrderRequest, Side, Trade

class UnifiedAggressiveBot(BaseBot):
    def __init__(self, cmi_url: str, username: str, password: str):
        super().__init__(cmi_url, username, password)
        
        # 1. State Tracking
        self.market_state = {
            "TIDE_SPOT": {"bid": None, "ask": None},
            "WX_SPOT": {"bid": None, "ask": None},
            "LHR_COUNT": {"bid": None, "ask": None},
            "LON_ETF": {"bid": None, "ask": None}
        }
        
        # Tracks local positions for Group A (4x Multiplier products)
        self.positions = {
            "TIDE_SPOT": 0, "WX_SPOT": 0, "LHR_COUNT": 0, "LON_ETF": 0
        }
        
        # 2. Timing Controls (Shared API Rate Limiting)
        self.last_api_call = 0.0
        self.last_maker_refresh = 0.0
        
        # 3. Strategy Parameters
        self.ARB_PROFIT_MARGIN = 50
        self.MAKER_SPREAD_WIDTH = 20
        self.MAKER_ORDER_VOLUME = 10
        self.MAKER_REFRESH_RATE = 4.0 # Seconds between replacing maker quotes
        
        # 4. Macro Fair Values (UPDATE THESE BASED ON LIVE DATA)
        self.theos = {
            "WX_SPOT": 4556,       
            "LHR_COUNT": 1250,     
            "TIDE_SPOT": 2341      
        }
        self.theos["LON_ETF"] = self.theos["WX_SPOT"] + self.theos["LHR_COUNT"] + self.theos["TIDE_SPOT"]

    def on_trades(self, trade: Trade) -> None:
        """Update inventory seamlessly on every fill. 
        Calculates side manually to avoid AttributeError."""
        if trade.product in self.positions:
            side = ""
            if trade.buyer == self.username:
                self.positions[trade.product] += trade.volume
                side = "BUY"
            elif trade.seller == self.username:
                self.positions[trade.product] -= trade.volume
                side = "SELL"
            
            if side:
                print(f"$$$ FILL: {side} {trade.volume} {trade.product} @ {trade.price} | Pos: {self.positions[trade.product]}")

    def on_orderbook(self, ob: OrderBook) -> None:
        """The Main Event Loop: Triggers every time the market ticks"""
        if ob.product not in self.market_state:
            return

        # Safely pull top-of-book
        best_bid = ob.buy_orders[0].price if ob.buy_orders else None
        best_ask = ob.sell_orders[0].price if ob.sell_orders else None
        self.market_state[ob.product] = {"bid": best_bid, "ask": best_ask}
        
        # PRIORITY 1: Check for guaranteed Arbitrage (Taker)
        arb_found = self.check_arbitrage()
        
        # PRIORITY 2: Manage our resting quotes (Maker)
        if not arb_found:
            self.run_market_maker()

    def check_arbitrage(self) -> bool:
        """The Mistake Catcher Logic"""
        if time.time() - self.last_api_call < 1.1:
            return False

        try:
            t_ask, t_bid = self.market_state["TIDE_SPOT"]["ask"], self.market_state["TIDE_SPOT"]["bid"]
            w_ask, w_bid = self.market_state["WX_SPOT"]["ask"], self.market_state["WX_SPOT"]["bid"]
            l_ask, l_bid = self.market_state["LHR_COUNT"]["ask"], self.market_state["LHR_COUNT"]["bid"]
            e_ask, e_bid = self.market_state["LON_ETF"]["ask"], self.market_state["LON_ETF"]["bid"]
        except KeyError:
            return False

        if None in (t_ask, w_ask, l_ask, e_bid, t_bid, w_bid, l_bid, e_ask):
            return False

        # Scenario A: ETF is overpriced
        synthetic_ask = t_ask + w_ask + l_ask
        if (e_bid - synthetic_ask) > self.ARB_PROFIT_MARGIN:
            print(f"[ARB A] Sniping! Buy Components, Sell ETF | Profit: {e_bid - synthetic_ask}")
            self.execute_arbitrage_trade(Side.SELL, e_bid, Side.BUY, t_ask, w_ask, l_ask)
            return True

        # Scenario B: ETF is underpriced
        synthetic_bid = t_bid + w_bid + l_bid
        if (synthetic_bid - e_ask) > self.ARB_PROFIT_MARGIN:
            print(f"[ARB B] Sniping! Buy ETF, Sell Components | Profit: {synthetic_bid - e_ask}")
            self.execute_arbitrage_trade(Side.BUY, e_ask, Side.SELL, t_bid, w_bid, l_bid)
            return True

        return False

    def execute_arbitrage_trade(self, etf_side: Side, etf_price: float, comp_side: Side, tide_p: float, wx_p: float, lhr_p: float):
        self.last_api_call = time.time()
        
        orders = [
            OrderRequest("LON_ETF", etf_price, etf_side, 1),
            OrderRequest("TIDE_SPOT", tide_p, comp_side, 1),
            OrderRequest("WX_SPOT", wx_p, comp_side, 1),
            OrderRequest("LHR_COUNT", lhr_p, comp_side, 1)
        ]

        responses = self.send_orders(orders)
        # IOC Cleanup
        for resp in responses:
            if resp.volume > resp.filled:
                self.cancel_order(resp.id)

    def run_market_maker(self) -> None:
        """The Aggressive Yo-Yo Quoting Logic"""
        if time.time() - self.last_maker_refresh < self.MAKER_REFRESH_RATE:
            return
            
        if time.time() - self.last_api_call < 1.1:
            return

        self.last_maker_refresh = time.time()
        self.last_api_call = time.time()

        # Clear old resting orders
        self.cancel_all_orders()

        orders_to_send = []

        # Target ONLY the 4x Multiplier Group A products [cite: 805]
        for product in ["TIDE_SPOT", "WX_SPOT", "LHR_COUNT", "LON_ETF"]:
            theo = self.theos[product]
            current_pos = self.positions[product]
            
            # Inventory Skew: Adjust prices up if short, down if long
            skew = (current_pos / 100.0) * 15 
            adjusted_theo = theo - skew
            
            bid_price = math.floor(adjusted_theo - (self.MAKER_SPREAD_WIDTH / 2))
            ask_price = math.ceil(adjusted_theo + (self.MAKER_SPREAD_WIDTH / 2))

            # Place orders safely within the +/- 100 limit 
            if current_pos < 90:
                orders_to_send.append(OrderRequest(product, bid_price, Side.BUY, self.MAKER_ORDER_VOLUME))
            if current_pos > -90:
                orders_to_send.append(OrderRequest(product, ask_price, Side.SELL, self.MAKER_ORDER_VOLUME))

        if orders_to_send:
            self.send_orders(orders_to_send)

if __name__ == "__main__":
    # --- CHALLENGE URL AND CREDENTIALS ---
    CHALLENGE_URL = "http://ec2-52-19-74-159.eu-west-1.compute.amazonaws.com/" 
    USERNAME = "45clubs"
    PASSWORD = "chudgoon"
    
    bot = UnifiedAggressiveBot(CHALLENGE_URL, USERNAME, PASSWORD)
    
    # Sync positions
    print("Syncing starting inventory from exchange...")
    starting_positions = bot.get_positions()
    for product in bot.positions.keys():
        bot.positions[product] = starting_positions.get(product, 0)
    print(f"Synced inventory: {bot.positions}")
        
    print("Starting Unified Aggressive Bot (Arbitrage + Market Making)...")
    bot.start()
    
    try:
        while True:
            time.sleep(1) 
    except KeyboardInterrupt:
        print("\nHalting bot. Canceling open orders...")
        bot.cancel_all_orders()
        bot.stop()
from bot_template import *


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
    
    
    

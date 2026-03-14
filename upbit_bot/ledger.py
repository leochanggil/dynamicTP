import os, csv
from datetime import datetime

class TradeLedger:
    def __init__(self, out_dir: str):
        self.out_dir = out_dir
        os.makedirs(out_dir, exist_ok=True)
        d = datetime.now().strftime("%Y%m%d")
        self.path = os.path.join(out_dir, f"trades_{d}.csv")

        if not os.path.exists(self.path):
            with open(self.path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow([
                    "mode", "time_entry", "time_exit", "market", "reason",
                    "entry", "exit", "volume", "gross", "fee", "net"
                ])

    def close_trade(self, mode: str, time_entry, time_exit, market: str, reason: str, entry: float, exit_: float, volume: float, fee_rate: float) -> float:
        gross = (exit_ - entry) * volume
        fee = (entry * volume + exit_ * volume) * fee_rate
        net = gross - fee

        with open(self.path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                mode, time_entry, time_exit, market, reason, 
                round(entry, 4), round(exit_, 4), volume, round(gross, 2), round(fee, 2), round(net, 2)
            ])
        return net
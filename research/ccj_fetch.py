"""Download daily OHLC for the CCJ correlation universe (2019-01-01 .. today)."""
import pickle, time, yfinance as yf, pandas as pd

UNIV = {
 # uranium / nuclear
 "CCJ":"Cameco (US)", "CCO.TO":"Cameco (Toronto)", "URNM":"Uranium miners ETF", "URA":"Uranium ETF",
 "U-UN.TO":"Sprott Physical Uranium", "YCA.L":"Yellow Cake", "KAP.L":"Kazatomprom", "PDN.AX":"Paladin",
 "BOE.AX":"Boss Energy", "NXE":"NexGen", "DNN":"Denison", "UEC":"Uranium Energy", "UUUU":"Energy Fuels",
 "LEU":"Centrus", "BWXT":"BWX Tech", "CEG":"Constellation", "VST":"Vistra", "TLN":"Talen",
 "OKLO":"Oklo", "SMR":"NuScale", "9501.T":"Tokyo Electric", "9503.T":"Kansai Electric",
 "7011.T":"Mitsubishi Heavy", "034020.KS":"Doosan Enerbility", "1816.HK":"CGN Power", "BN":"Brookfield",
 "BEP":"Brookfield Renewable",
 # AI power / chips
 "ETN":"Eaton", "VRT":"Vertiv", "GEV":"GE Vernova", "PWR":"Quanta", "TSM":"TSMC", "NVDA":"NVIDIA", "SMH":"Semis ETF",
 # commodities
 "CL=F":"Oil", "NG=F":"Natural gas", "BTU":"Peabody coal", "HG=F":"Copper", "GC=F":"Gold", "SI=F":"Silver",
 # FX & rates
 "CAD=X":"USD/CAD", "JPY=X":"USD/JPY", "KZT=X":"USD/KZT", "^TNX":"US 10y yield", "DX-Y.NYB":"Dollar index",
 # indices
 "SPY":"S&P 500", "QQQ":"Nasdaq 100", "^GSPTSE":"TSX", "^N225":"Nikkei", "^KS11":"KOSPI", "^HSI":"Hang Seng",
 "^AXJO":"ASX 200", "^STOXX50E":"Euro Stoxx 50", "XLU":"US utilities",
 # crypto
 "BTC-USD":"Bitcoin", "ETH-USD":"Ether",
}

if __name__ == "__main__":
    out = {}
    tick = list(UNIV)
    for i in range(0, len(tick), 12):
        chunk = tick[i:i+12]
        for attempt in range(3):
            try:
                d = yf.download(chunk, start="2019-01-01", auto_adjust=True, progress=False, group_by="ticker", threads=True)
                break
            except Exception as e:
                print("retry", e); time.sleep(5)
        for t in chunk:
            try:
                df = d[t][["Open", "High", "Low", "Close"]].dropna(how="all")
                if len(df) > 50: out[t] = df
                else: print("thin", t, len(df))
            except Exception as e:
                print("miss", t, e)
        time.sleep(2)
    pickle.dump(out, open("ccj_univ.pkl", "wb"))
    for t, df in out.items():
        print(f"{t:12s} {len(df):5d} {df.index[0].date()} {df.index[-1].date()}")

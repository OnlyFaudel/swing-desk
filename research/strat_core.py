import numpy as np, pandas as pd
def rsi(c,n):
    d=c.diff(); up=d.clip(lower=0).ewm(alpha=1/n,adjust=False).mean(); dn=(-d.clip(upper=0)).ewm(alpha=1/n,adjust=False).mean()
    return 100-100/(1+up/dn.replace(0,np.nan))
def add_ind(df):
    df=df[["Open","High","Low","Close","Volume"]].copy()
    df["sma50"]=df.Close.rolling(50).mean(); df["rsi2"]=rsi(df.Close,2)
    pc=df.Close.shift(); tr=pd.concat([df.High-df.Low,(df.High-pc).abs(),(df.Low-pc).abs()],axis=1).max(axis=1)
    df["atr"]=tr.rolling(14).mean(); df["hi20"]=df.Close.rolling(20).max()
    return df

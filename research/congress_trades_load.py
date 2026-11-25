import json, pandas as pd, numpy as np
h=pd.DataFrame(json.load(open('/tmp/cong/house/data/all_transactions.json')))
h['who']=h.representative; h['chamber']='House'
s=pd.DataFrame(json.load(open('/tmp/cong/senate.json'))); s['who']=s.senator; s['chamber']='Senate'; s['disclosure_date']=None
d=pd.concat([h[['transaction_date','disclosure_date','ticker','type','amount','who','chamber','owner']],s[['transaction_date','disclosure_date','ticker','type','amount','who','chamber','owner']]])
d['tx']=pd.to_datetime(d.transaction_date,errors='coerce',format='mixed'); d['disc']=pd.to_datetime(d.disclosure_date,errors='coerce',format='mixed')
d=d[d.tx.notna()&d.ticker.notna()&(d.ticker.str.len().between(1,5))&(d.ticker!='--')]
d['ticker']=d.ticker.str.upper().str.replace('.','-',regex=False)
d['buy']=d.type.str.contains('Purchase',case=False); d['sell']=d.type.str.contains('Sale',case=False)
d['lag']=(d.disc-d.tx).dt.days
d.to_pickle('/tmp/congwork/trades.pkl')
if __name__=='__main__':
    print(len(d), d.groupby('chamber').tx.agg(['min','max','count']))
    print('house lag days', d[d.chamber=='House'].lag.describe().round(1).to_dict())
    print('zero-lag share', (d[d.chamber=='House'].lag==0).mean().round(3))
    print(d.groupby(d.tx.dt.year).size().to_dict())
    NUC=['CCJ','NXE','UEC','DNN','UUUU','LEU','BWXT','CEG','VST','TLN','OKLO','SMR','NNE','URG','GEV','URA','URNM','NLR']
    n=d[d.ticker.isin(NUC)]; print('nuclear trades',len(n)); print(n.groupby(['ticker','buy']).size().unstack(fill_value=0))
    print(n.sort_values('tx').tail(12)[['tx','disc','ticker','type','amount','who']].to_string())
    p=d[d.who.str.contains('Pelosi',na=False)]; print('Pelosi',len(p), p.tx.min(), p.tx.max())

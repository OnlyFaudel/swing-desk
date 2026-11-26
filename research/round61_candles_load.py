import pandas as pd, numpy as np, glob, os
def load(path='/home/claude/swing-desk/data/candles15'):
    fs=sorted(glob.glob(os.path.join(path,'*.csv.gz')))
    d=pd.concat([pd.read_csv(f) for f in fs])
    d['date']=d.ts.str[:10]; d['k']=((pd.to_datetime(d.ts).dt.hour*60+pd.to_datetime(d.ts).dt.minute)-570)//15
    d=d[(d.k>=0)&(d.k<26)]
    n=d.groupby(['t','date']).k.transform('size'); d=d[n==26]
    out={}
    for f in ('open','high','low','close','volume','vwap'):
        p=d.pivot_table(index=['t','date'],columns='k',values=f,aggfunc='first').sort_index()
        out[f]=p
    return out
if __name__=='__main__':
    o=load(); c=o['close']; print(c.shape, c.index.get_level_values(0).value_counts().to_dict())
    pd.to_pickle(o,'/tmp/r61/c15.pkl')

import pandas as pd, numpy as np, yfinance as yf, warnings, json; warnings.filterwarnings("ignore")
g=yf.download('^GSPC',start='1950-01-01',auto_adjust=True,progress=False)
gc=g['Close'].squeeze().dropna(); go=g['Open'].squeeze()
idx=gc.index
bd=pd.bdate_range(idx[0],idx[-1]); I=set(idx)
hol=[d for d in bd if d not in I and not (d.year==2001 and d.month==9) and not (d.year==2012 and d.month==10 and d.day in (29,30))]
# drop multi-day closures and keep one per holiday
hol=[h for k,h in enumerate(hol) if k==0 or (h-hol[k-1]).days>3]
def name(h):
    m=h.month
    if m==11: return 'Thanksgiving'
    if m==12: return 'Christmas'
    if m==1: return 'New Year/MLK'
    if m in (3,4): return 'Good Friday'
    if m==5: return 'Memorial Day'
    if m==7: return 'July 4'
    if m==9: return 'Labor Day'
    if m==2: return 'Presidents Day'
    return 'other'
r=gc.pct_change()
rows=[]
for h in hol:
    a=idx.searchsorted(h)       # first session after
    if a<5 or a+5>=len(idx): continue
    rows.append(dict(h=h,name=name(h),era='1950-89' if h.year<1990 else ('1990-2007' if h.year<2008 else '2008-26'),
        pre3=gc.iloc[a-1]/gc.iloc[a-4]-1, pre1=r.iloc[a-1], post1=r.iloc[a], post5=gc.iloc[a+4]/gc.iloc[a-1]-1))
D=pd.DataFrame(rows)
mask=np.ones(len(idx),bool)
for h in hol:
    a=idx.searchsorted(h); mask[max(0,a-4):a+5]=False
base1=r[mask].mean(); base3=(gc.pct_change(3)[mask]).mean(); base5=(gc.pct_change(5)[mask]).mean()
print(f"S&P 500 1950-2026: {len(D)} holidays")
print(f"{'':28s}{'last 3 days before':>20s}{'last day before':>17s}{'first day after':>17s}{'5 days after':>14s}")
print(f"{'ordinary days':28s}{base3*100:+19.2f}%{base1*100:+16.2f}%{base1*100:+16.2f}%{base5*100:+13.2f}%")
for e,x in D.groupby('era'):
    print(f"{'holidays '+e:28s}{x.pre3.mean()*100:+19.2f}%{x.pre1.mean()*100:+16.2f}%{x.post1.mean()*100:+16.2f}%{x.post5.mean()*100:+13.2f}%   up before: {(x.pre1>0).mean()*100:.0f}% of the time")
print("\nLast day before, by holiday (all years):", D.groupby('name').pre1.mean().mul(100).round(2).to_dict())
print("First day after, by holiday:", D.groupby('name').post1.mean().mul(100).round(2).to_dict())
# strategy: sell at close 3 days before, buy back at close of last day before vs day after
print("\nDad's trade (sell 3 days before, buy back at the first close after) vs just holding:")
for e,x in D.groupby('era'):
    hold=(1+x.pre3)*(1+x.post1)-1; # holding through
    # being out means missing pre3 and post1 -> gain from being out = -(that)
    print(f"  {e}: holding through earned {hold.mean()*100:+.2f}% on average; selling and rebuying would have missed that (and paid costs). Worked {(hold<0).mean()*100:.0f}% of holidays")
# our stocks
W=pd.read_pickle('/tmp/wide/wide.pkl')['Close']
NUC=[t for t in ["CCJ","NXE","UEC","DNN","UUUU","LEU","BWXT","CEG","VST","TLN"] if t in W]
N=pd.read_pickle('/tmp/sz/daily_max.pkl')['Close']
B=pd.concat([W[[t for t in NUC if t in W]], N[[t for t in NUC if t not in W and t in N]]],axis=1).reindex(W.index)
br=B.pct_change().mean(axis=1); bi=br.index
rows=[]
for h in hol:
    if h.year<2008: continue
    a=bi.searchsorted(h)
    if a<5 or a+5>=len(bi): continue
    rows.append(dict(era='2008-18' if h.year<2019 else '2019-26',pre3=(1+br.iloc[a-3:a]).prod()-1,pre1=br.iloc[a-1],post1=br.iloc[a]))
E=pd.DataFrame(rows); m2=np.ones(len(bi),bool)
for h in hol:
    a=bi.searchsorted(h); m2[max(0,a-4):a+5]=False
print(f"\nOur 10 nuclear stocks (average), ordinary day {br[m2].mean()*100:+.2f}%:")
for e,x in E.groupby('era'): print(f"  {e}: last 3 days before {x.pre3.mean()*100:+.2f}%, last day before {x.pre1.mean()*100:+.2f}%, first day after {x.post1.mean()*100:+.2f}% (n {len(x)})")

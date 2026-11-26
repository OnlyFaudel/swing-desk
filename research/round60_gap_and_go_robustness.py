exec(open('day.py').read().split('print("All long-only')[0])
def stats(x,label):
    s=[]
    for e in ('2016-18','2019-26'):
        g=x[x.era==e]
        if len(g)<5: s.append(f"{e} n {len(g)}"); continue
        d=g.groupby('date').r.mean(); s.append(f"{e} {g.r.mean()*100:+.2f}% (n {len(g)}, t {d.mean()/(d.std()/np.sqrt(len(d))):.1f})")
    print(f"  {label}: "+" | ".join(s))
print("Gap-and-go robustness (buy 9:35, sell close):")
for k in (0.02,0.03,0.05,0.08):
    x=I[(I.gap>=k)&(I.px935>I.open)].copy(); x['r']=x.close/x.px935-1-x.cost; stats(x,f"gap {k*100:.0f}%+")
x=I[(I.gap>=0.03)].copy(); x['r']=x.close/x.px935-1-x.cost; stats(x,"gap 3%+, no 9:35 condition")
x=I[(I.gap>=0.03)&(I.px935>I.open)].copy(); x['r']=x.close/x.px935-1-x.cost
stats(x[~x.date.dt.year.isin([2020,2021])],"gap 3%+, without 2020-21 (meme/COVID years)")
x2=x.copy(); x2['r']=x2.r-0.002; stats(x2,"gap 3%+, double the costs")
x3=I[(I.gap>=0.03)&(I.px935>I.open)].copy(); x3['r']=x3.px1530/x3.px935-1-x3.cost; stats(x3,"gap 3%+, sell 3:30 instead of close")
print("  by stock (2019-26):", x[x.era=='2019-26'].groupby('t').r.mean().mul(100).round(2).to_dict())
print("  by year:", x.groupby(x.date.dt.year).r.mean().mul(100).round(2).to_dict())

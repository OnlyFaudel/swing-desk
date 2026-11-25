import pandas as pd, numpy as np
I=pd.read_pickle('/tmp/r15/intraday.pkl'); I['date']=pd.to_datetime(I.date); I=I.sort_values(['t','date'])
D=pd.read_pickle('/tmp/sz/daily_max.pkl'); so,sc=D['Open']['SPY'],D['Close']['SPY']; cost=0.002
I['prev']=I.groupby('t').close.shift(1); I['nclose']=I.groupby('t').close.shift(-1); I['nopen']=I.groupby('t').open.shift(-1)
I['c10']=I.groupby('t').close.shift(-10); I['v20']=I.groupby('t').vol.transform(lambda s:s.rolling(20).mean().shift(1))
I['r5']=I.close/I.groupby('t').close.shift(5)-1
spy_oc=(sc/so-1); spy_cc=sc.pct_change()
def era(df,col,label):
    out=[]
    for e,m in (('2016-18',df.date.dt.year<=2018),('2019-26',df.date.dt.year>=2019)):
        y=df[m][col].dropna(); out.append(f'{e} n={len(y):4d} {y.mean()*100:+.2f}% (t {y.mean()/y.std()*np.sqrt(len(y)) if len(y)>2 else 0:.1f}, up {(y>0).mean()*100:.0f}%)')
    print(f'{label:58s} '+' | '.join(out))
# TEST 1: gap-down 5%+ at the open: buy 9:35 / 9:45 -> that close (vs S&P open->close)
g=I[(I.open/I.prev-1)<=-0.05].copy(); g['spy']=g.date.map(spy_oc)
for px in ('px935','px945'):
    g[f'x_{px}']=(g.close/g[px]-1)-g.spy-cost
era(g,'x_px935','1 gap-down 5%+: buy 9:35 -> close (all)')
era(g[g.press15>0],'x_px935','1 ... first 15 min buying pressure > 0')
era(g[g.press15<=0],'x_px935','1 ... first 15 min selling pressure')
era(g[g.press15>0],'x_px945','1 ... pressure > 0, buy 9:45 -> close')
# TEST 2: sharp 5-day drop 15%+: heavy vs light selling on the drop day -> 10 days
s=I[I.r5<=-0.15].copy(); s['x10']=(s.c10/s.close-1)-cost
s=s.sort_values('date').groupby('t',group_keys=False).apply(lambda d:d[d.date.diff().dt.days.fillna(99)>=10])
era(s,'x10','2 sharp drop 15% in 5 days -> 10 days (absolute)')
era(s[s.press_day<=-0.2],'x10','2 ... heavy selling pressure that day')
era(s[s.press_day>-0.2],'x10','2 ... light selling pressure')
era(s[s.vol>=2*s.v20],'x10','2 ... volume 2x+ its 20-day average')
# TEST 3: last-30-minute pressure -> next day
I['spyn']=I.date.map(spy_cc.shift(-1)); I['x_nc']=(I.nclose/I.close-1)-I.spyn-cost; I['x_no']=(I.nopen/I.close-1)
era(I[I.press_last30>=0.4],'x_nc','3 strong buying last 30 min -> next close vs S&P')
era(I[I.press_last30<=-0.4],'x_nc','3 strong selling last 30 min -> next close vs S&P')
era(I[I.press_last30>=0.4],'x_no','3 strong buying last 30 min -> next open (gap)')
# TEST 5: after hours: move 3%+ from the 4 PM close -> next open, next close
a=I[I.ah_px.notna()].copy(); a['ah']=a.ah_px/a.close-1
a['to_open']=a.nopen/a.ah_px-1; a['to_close']=a.nclose/a.ah_px-1
for lab,m in (('up 3%+',a.ah>=0.03),('down 3%+',a.ah<=-0.03),('up 5%+',a.ah>=0.05),('down 5%+',a.ah<=-0.05)):
    era(a[m],'to_open',f'5 after hours {lab} -> next OPEN vs after-hours price')
    era(a[m],'to_close',f'5 after hours {lab} -> next CLOSE vs after-hours price')

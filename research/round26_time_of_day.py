import pandas as pd, numpy as np
x=pd.read_pickle('/tmp/r15/intraday.pkl').sort_values(['t','date']); x['date']=pd.to_datetime(x.date)
g=x.groupby('t'); x['r5']=g.close.shift(1)/g.close.shift(6)-1; x['gap']=x.open/g.close.shift(1)-1
x['ten_to_close']=x.close/x.px1000-1; x['open_to_ten']=x.px1000/x.open-1; x['c1530_to_close']=x.close/x.px1530-1
for lab,m in (('all days',x.r5.notna()),('after +10% in 5 days (like a target-hit exit)',x.r5>0.10),('after -10% in 5 days',x.r5<-0.10),('gap up 3%+ today',x.gap>0.03),('gap down 3%+ today',x.gap<-0.03)):
    out=[]
    for era,(a,b) in {'16-20':('2016','2021'),'21-26':('2021','2027')}.items():
        y=x[m&(x.date>=a)&(x.date<b)]
        out.append(f"{era}: open->10:00 {y.open_to_ten.mean()*100:+.2f}% | 10:00->close {y.ten_to_close.mean()*100:+.2f}% | 15:30->close {y.c1530_to_close.mean()*100:+.2f}% n{len(y)}")
    print(f"{lab:44s}",' || '.join(out))

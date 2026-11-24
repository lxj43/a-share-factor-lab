#!/usr/bin/env python3
"""Add an equal-weight rank composite to the JQData demo using its cached inputs."""
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd
from jqdata_local import BASE, NAMES, build_factors, composite_score, simulate, stats
from refresh_factor_page import refresh


def main():
    data=json.loads((BASE/'factor_data.json').read_text())
    if data['meta'].get('provider')!='JQData':raise ValueError('Requires JQData dataset')
    out=Path(data['meta']['audit_dir'])
    raw=pd.read_csv(out/'prices_adjusted.csv',parse_dates=['time'])
    px={field:raw.pivot(index='time',columns='code',values=field).sort_index()
        for field in ['open','close','paused','high_limit','low_limit']}
    pools=json.loads((out/'universe.json').read_text())
    factors=build_factors(px)
    selections, snapshots, attribution={},[],[]
    for execution, info in pools.items():
        sig=pd.Timestamp(info['signal_date']); day=pd.Timestamp(execution)
        row=composite_score(factors,sig,info['stocks'],px['paused'].loc[sig])
        if len(row)<10:raise ValueError('Insufficient common sample')
        row=row.sort_index().sort_values(ascending=False,kind='mergesort')
        selections[day]=row.head(max(1,math.floor(len(row)*data['meta']['top_pct']))).index.tolist()
        snapshots.extend(['MULTI',str(sig.date()),execution,c,float(v),c in selections[day]] for c,v in row.items())
        cross=pd.DataFrame({k:f.loc[sig].reindex(row.index) for k,f in factors.items()})
        ranks=cross.rank(method='average',pct=True)
        for c in row.index:
            attribution.append({'signal_date':str(sig.date()),'execution_date':execution,'code':c,
                                'score':float(row[c]),'selected':c in selections[day],
                                **{k+'_rank':float(ranks.loc[c,k]) for k in factors}})
    dates=pd.DatetimeIndex(data['dates'][1:])
    curve,trades,holds=simulate(px,selections,dates)
    values=[1.]+curve
    combo={'key':'MULTI','name':NAMES['MULTI'],'values':values,'stats':stats(values)}
    data['series']=[s for s in data['series'] if s['key'] not in ['MULTI','BENCH']]+[combo]+[s for s in data['series'] if s['key']=='BENCH']
    data['meta']['composite']={'method':'共同有效样本内百分位排名等权平均','weights':{k:.2 for k in factors},'holding':'合成总分前20%等权；沿用原调仓与交易约束；未经权重优化'}
    for name,rows,cols in [
        ('trades',trades,['date','code','side','adjusted_units','adjusted_price','amount']),
        ('holdings',holds,['date','code','adjusted_units','adjusted_price','value'])]:
        path=out/(name+'.csv'); old=pd.read_csv(path)
        new=pd.DataFrame(rows,columns=cols);new.insert(0,'factor','MULTI')
        pd.concat([old.loc[old.factor!='MULTI'],new],ignore_index=True).to_csv(path,index=False)
    path=out/'factor_snapshots.csv';old=pd.read_csv(path)
    new=pd.DataFrame(snapshots,columns=old.columns)
    pd.concat([old.loc[old.factor!='MULTI'],new],ignore_index=True).to_csv(path,index=False)
    pd.DataFrame(attribution).to_csv(out/'composite_scores.csv',index=False)
    from factor_metrics import add_excess_metrics
    add_excess_metrics(data)
    dest=BASE/'factor_data_jq.json';dest.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False))
    refresh(dest)
    for s in data['series']:print(s['name'],s['stats'])
    print('Composite holdings per rebalance:',[len(v) for v in selections.values()])

if __name__=='__main__':main()

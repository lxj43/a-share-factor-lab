#!/usr/bin/env python3
"""Build an offline holdings explorer from the existing JQData audit files."""
import json
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent


def build_report(data, base=BASE):
    out=base/Path(data['meta']['audit_dir'])
    holdings=pd.read_csv(out/'holdings.csv')
    trades=pd.read_csv(out/'trades.csv')
    snapshots=pd.read_csv(out/'factor_snapshots.csv')
    raw=pd.read_csv(out/'prices_adjusted.csv')
    price=raw.set_index(['time','code'])
    names_path=out/'security_names.json'
    names=json.loads(names_path.read_text()) if names_path.exists() else {'as_of':None,'names':{}}
    codes=sorted(set(holdings.code)-{'CASH'} | set(snapshots.code))
    code_index={c:i for i,c in enumerate(codes)}
    factors=[{'key':s['key'],'name':s['name']} for s in data['series'] if s['key']!='BENCH']
    report={'meta':data['meta'],'factors':factors,'codes':codes,
            'names':[names['names'].get(c,'') for c in codes], 'names_as_of':names['as_of'],
            'dates':data['dates'][1:],'daily':{},'events':{},'schema_version':1}
    for f in factors:
        key=f['key'];df=holdings[holdings.factor==key]
        daily={}
        for day,group in df.groupby('date'):
            cash=float(group.loc[group.code=='CASH','value'].sum())
            stocks=group[group.code!='CASH']
            daily[day]={'cash':round(cash,6),'nav':round(float(group.value.sum()),6),
                'rows':[[code_index[r.code],float(r.adjusted_units),float(r.adjusted_price),float(r.value)] for r in stocks.itertuples()]}
        report['daily'][key]=daily
        events=[]
        for day,group in snapshots[snapshots.factor==key].groupby('execution_date'):
            sig=str(group.signal_date.iloc[0]);selected=set(group.loc[group.selected,'code'])
            ranked=group.sort_values('code').sort_values('factor_value',ascending=False,kind='mergesort')
            ranks={r.code:[i+1,float(r.factor_value)] for i,r in enumerate(ranked.itertuples())}
            index=report['dates'].index(day)
            prior=daily[report['dates'][index-1]] if index else {'cash':100000.,'rows':[]}
            current=daily[day]
            before={report['codes'][r[0]]:r for r in prior['rows']}
            after={report['codes'][r[0]]:r for r in current['rows']}
            daytrades=trades[(trades.factor==key)&(trades.date==day)]
            buy=daytrades.loc[daytrades.side=='BUY'].groupby('code').amount.sum().to_dict()
            sell=daytrades.loc[daytrades.side=='SELL'].groupby('code').amount.sum().to_dict()
            rows=[];opening_nav=prior['cash']
            # Cash and all positions marked at execution-day open, before trades.
            for c,r in before.items():
                op=price.loc[(day,c),'open']
                opening_nav+=r[1]*(float(op) if pd.notna(op) else r[2])
            for c in sorted(set(before)|set(after)|selected):
                q0=before[c][1] if c in before else 0.;q1=after[c][1] if c in after else 0.
                r=price.loc[(day,c)];op=float(r['open']) if pd.notna(r['open']) else (before[c][2] if c in before else 0.)
                delta=q1-q0
                if c not in selected and q1>1e-8:action='exit_blocked'
                elif q0<1e-8 and q1<1e-8:action='buy_blocked'
                elif q0<1e-8:action='new'
                elif q1<1e-8:action='exit'
                elif abs(delta)<=1e-8:action='hold'
                elif delta>0:action='increase'
                else:action='decrease'
                notes=[]
                if r['paused']!=0:notes.append('开盘停牌')
                if pd.notna(r['open']) and pd.notna(r['high_limit']) and r['open']>=r['high_limit']:notes.append('开盘涨停，限制买入')
                if pd.notna(r['open']) and pd.notna(r['low_limit']) and r['open']<=r['low_limit']:notes.append('开盘跌停，限制卖出')
                rank,value=ranks.get(c,[None,None])
                rows.append({'c':code_index[c],'rank':rank,'score':value,'selected':c in selected,
                    'action':action,'q0':q0,'q1':q1,'delta':delta,'open':op,
                    'before_weight':q0*op/opening_nav,'after_weight':q1*op/opening_nav,
                    'close_value':after[c][3] if c in after else 0.,
                    'buy':float(buy.get(c,0)),'sell':float(sell.get(c,0)),'note':'；'.join(notes)})
            events.append({'date':day,'signal_date':sig,'selected_count':len(selected),
                'opening_nav':opening_nav,'closing_nav':current['nav'],'cash':current['cash'],
                'buy':float(sum(buy.values())),'sell':float(sum(sell.values())),
                'rows':rows})
        report['events'][key]=events
    payload=json.dumps(report,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('</','<\\/')
    template=(base/'factor_holdings_template.html').read_text()
    dest=base/'factor_holdings.html'
    tmp=dest.with_suffix('.html.tmp');tmp.write_text(template.replace('__HOLDINGS_DATA__',payload));tmp.replace(dest)
    print('持仓页面已生成：',dest,'（%.1f MB）'%(dest.stat().st_size/1e6))
    return report

if __name__=='__main__':
    build_report(json.loads((BASE/'factor_data.json').read_text()))

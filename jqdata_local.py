#!/usr/bin/env python3
"""Local JQData research pipeline. Reads local credentials; no live orders."""
import argparse
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd
from research_factors import RESEARCH, build_research_factors

BASE = Path(__file__).resolve().parent
NAMES = {'REV5':'5日反转','MOM20':'20日动量','MOM60':'60日动量',
         'VOL60':'60日低波','OVERNIGHT':'隔夜收益','MULTI':'多因子组合策略'}


def simulate(prices, picks, dates, initial=100000):
    """Adjusted-price units; hold units between rebalances. No fees/lot rounding.
    picks maps execution day to selections made using previous day's information.
    Suspensions / opening limit prices prevent trades; residual cash is retained.
    """
    cash, units, marks = initial, {}, {}
    curve, trades, holdings = [], [], []
    for day in dates:
        op, cl = prices['open'].loc[day], prices['close'].loc[day]
        def tradable(code, buy):
            price = op.get(code, np.nan)
            paused = prices['paused'].loc[day].get(code, 1)
            limit = prices['high_limit' if buy else 'low_limit'].loc[day].get(code, np.nan)
            return (pd.notna(price) and price > 0 and paused == 0
                    and pd.notna(limit) and (price < limit if buy else price > limit))
        # Opening mark determines targets; existing units drift naturally each day.
        opening = {c: float(op[c]) if pd.notna(op.get(c)) else marks[c] for c in units}
        equity = cash + sum(q * opening[c] for c, q in units.items())
        if day in picks:
            selected = picks[day]
            target = equity / len(selected) if selected else 0
            for c in list(units):
                wanted = target / opening[c] if c in selected else 0
                qty = max(0, units[c] - wanted)
                if qty > 1e-10 and tradable(c, False):
                    amount = qty * float(op[c]); cash += amount; units[c] -= qty
                    trades.append([str(day.date()), c, 'SELL', qty, float(op[c]), amount])
                    if units[c] < 1e-10: del units[c]
            orders = []
            for c in selected:
                if tradable(c, True):
                    price = float(op[c]); amount = max(0, target - units.get(c, 0) * price)
                    orders.append((c, price, amount))
            scale = min(1, cash / sum(x[2] for x in orders)) if sum(x[2] for x in orders) else 0
            for c, price, amount in orders:
                amount *= scale
                if amount > 1e-8:
                    qty = amount / price; units[c] = units.get(c, 0) + qty; cash -= amount
                    marks[c] = price
                    trades.append([str(day.date()), c, 'BUY', qty, price, amount])
        for c in units:
            if pd.notna(cl.get(c)) and cl[c] > 0: marks[c] = float(cl[c])
            if c not in marks: raise ValueError('Missing valuation: %s %s' % (day, c))
            holdings.append([str(day.date()), c, units[c], marks[c], units[c]*marks[c]])
        value = cash + sum(q * marks[c] for c, q in units.items())
        holdings.append([str(day.date()), 'CASH', 1, cash, cash])
        curve.append(value / initial)
    return curve, trades, holdings


def stats(values):
    x = np.array(values, dtype=float)
    return {'total': round((x[-1]-1)*100, 2),
            'ann': round((x[-1]**(250/(len(x)-1))-1)*100, 2),
            'mdd': round(np.max(1-x/np.maximum.accumulate(x))*100, 2)}




def build_factors(px):
    close, op = px['close'], px['open']
    ret = close.pct_change(fill_method=None)
    factors = {'REV5':-(close/close.shift(5)-1), 'MOM20':close/close.shift(20)-1,
               'MOM60':close/close.shift(60)-1, 'VOL60':-ret.rolling(60).std(),
               'OVERNIGHT':(op/close.shift(1)).rolling(20).apply(np.prod,raw=True)-1}
    return factors


def composite_score(factors, signal_date, pool, paused):
    """Equal mean of percentile ranks on the common valid, unpaused universe.
    All component signs already mean 'higher is preferred'; no fitted weights.
    """
    cross = pd.DataFrame({key: frame.loc[signal_date].reindex(pool)
                          for key, frame in factors.items() if frame is not None})
    cross = cross.replace([np.inf, -np.inf], np.nan).dropna(how='any')
    cross = cross.loc[paused.reindex(cross.index).eq(0)]
    return cross.rank(method='average', pct=True).mean(axis=1)



def select_stocks(factor, prices, signals, pools, top_pct, key, components=None):
    selections, records = {}, []
    for day, signal in signals.items():
        paused = prices['paused'].loc[signal]
        if components is None:
            row = factor.loc[signal].reindex(pools[day])
            row = row.replace([np.inf, -np.inf], np.nan).dropna()
        else:
            row = composite_score(components, signal, pools[day], paused)
        row = row[paused.reindex(row.index).eq(0)]
        if len(row) < 10:
            raise ValueError(f'有效因子样本不足: {key} {signal}')
        row = row.sort_index().sort_values(ascending=False, kind='mergesort')
        picks = row.head(max(1, math.floor(len(row) * top_pct))).index
        selections[day] = picks.tolist()
        records.extend([key, str(signal.date()), str(day.date()), code, float(value), code in picks]
                       for code, value in row.items())
    return selections, records


def load_credentials(path):
    """Read credentials without displaying them or prompting interactively."""
    path = Path(path).expanduser()
    if not path.is_file():
        raise ValueError('找不到聚宽账号配置文件，请创建 jqdata_credentials.json')
    path.chmod(0o600)
    try:
        config = json.loads(path.read_text(encoding='utf-8-sig'))
    except (ValueError, UnicodeError):
        raise ValueError('聚宽账号配置必须是有效的 UTF-8 JSON；请检查双引号和逗号') from None
    if not isinstance(config, dict):
        raise ValueError('聚宽账号配置必须包含 username 和 password 字段')
    user, password = config.get('username'), config.get('password')
    if not isinstance(user, str) or not user.strip() or not isinstance(password, str) or not password:
        raise ValueError('请先在 jqdata_credentials.json 中填写 username 和 password')
    return user.strip(), password


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials', default=str(BASE / 'jqdata_credentials.json'))
    parser.add_argument('--start', default='2025-08-15')
    parser.add_argument('--end', default='2026-07-15')
    parser.add_argument('--rebalance', type=int, default=20)
    parser.add_argument('--top-pct', type=float, default=.2)
    args = parser.parse_args()
    if args.rebalance < 1 or not 0 < args.top_pct <= 1: parser.error('Invalid selection parameters')
    import jqdatasdk as jq
    user, password = load_credentials(args.credentials)
    jq.auth(user, password)
    del password
    if not jq.is_auth(): raise RuntimeError('聚宽认证失败')
    print('认证成功。剩余查询额度:', jq.get_query_count())
    warm = pd.Timestamp(args.start) - pd.Timedelta(days=220)
    calendar = pd.DatetimeIndex(pd.to_datetime(jq.get_trade_days(start_date=warm.date(), end_date=args.end)))
    display_days = calendar[calendar >= pd.Timestamp(args.start)]
    if len(display_days) < 2: raise ValueError('区间内交易日不足，请检查账号数据权限和日期')
    # Anchor NAV at the first requested trading day's close. First execution is
    # the following session's open, using information known at that close.
    baseline, bt = display_days[0], display_days[1:]
    execution = bt[::args.rebalance]
    signals = {d: calendar[calendar.get_loc(d)-1] for d in execution}
    pools = {}
    for d, sig in signals.items():
        pools[d] = jq.get_index_stocks('000300.XSHG', date=sig.date())
    securities = sorted(set(c for pool in pools.values() for c in pool))
    print('获取沪深300历史样本，联合股票数:', len(securities))
    outdir = BASE / 'data' / ('jqdata_' + baseline.strftime('%Y%m%d') + '_' + bt[-1].strftime('%Y%m%d'))
    outdir.mkdir(parents=True, exist_ok=True)
    try:
        security_names = {}
        for name_date in [baseline.date(), bt[-1].date()]:
            security_names.update(jq.get_all_securities(types=['stock'], date=name_date)['display_name'].to_dict())
        (outdir/'security_names.json').write_text(json.dumps({'as_of':str(bt[-1].date()),'names':security_names}, ensure_ascii=False))
    except Exception:
        print('证券名称暂未获取，持仓页面仍显示证券代码。')
    fields = ['open','close','paused','high_limit','low_limit']
    chunks = []
    for i in range(0, len(securities), 20):
        frame = jq.get_price(securities[i:i+20], start_date=warm.date(), end_date=bt[-1].date(),
                             fields=fields, fq='pre', panel=False, round=False)
        chunks.append(frame)
        print('行情进度 %d/%d' % (min(i+20, len(securities)),len(securities)))
    raw = pd.concat(chunks, ignore_index=True)
    raw['time'] = pd.to_datetime(raw['time'])
    raw.to_csv(outdir/'prices_adjusted.csv', index=False)
    (outdir/'universe.json').write_text(json.dumps({str(d.date()):{'signal_date':str(signals[d].date()),'stocks':pools[d]} for d in execution},ensure_ascii=False,indent=2))
    px = {f:raw.pivot(index='time',columns='code',values=f).reindex(calendar) for f in fields}
    core_factors = build_factors(px)
    factors = {**core_factors, 'MULTI': None, **build_research_factors(px['close'])}
    series, alltrades, allholdings, snapshots = [], [], [], []
    dates = [baseline] + list(bt)
    for key, factor in factors.items():
        selections, records = select_stocks(factor, px, signals, pools, args.top_pct, key,
                                            core_factors if key == 'MULTI' else None)
        snapshots.extend(records)
        curve,trades,holds = simulate(px,selections,bt)
        values = [1.] + curve
        series.append({'key':key,'name':RESEARCH[key]['name'] if key in RESEARCH else NAMES[key],'values':values,'stats':stats(values)})
        alltrades.extend([key]+r for r in trades); allholdings.extend([key]+r for r in holds)
    benchmark = jq.get_price('000300.XSHG',start_date=baseline.date(),end_date=bt[-1].date(),fields=['close'],fq=None)
    benchmark.index = pd.to_datetime(benchmark.index)
    b = benchmark['close'].reindex(dates)
    if b.isna().any(): raise ValueError('基准日期不完整')
    values = (b/b.iloc[0]).tolist()
    series.append({'key':'BENCH','name':'沪深300价格指数','values':values,'stats':stats(values)})
    pd.DataFrame(alltrades,columns=['factor','date','code','side','adjusted_units','adjusted_price','amount']).to_csv(outdir/'trades.csv',index=False)
    pd.DataFrame(allholdings,columns=['factor','date','code','adjusted_units','adjusted_price','value']).to_csv(outdir/'holdings.csv',index=False)
    pd.DataFrame(snapshots,columns=['factor','signal_date','execution_date','code','factor_value','selected']).to_csv(outdir/'factor_snapshots.csv',index=False)
    result = {'meta':{'source':'聚宽 JQData / 沪深300历史成分','provider':'JQData',
        'start':str(baseline.date()),'end':str(bt[-1].date()),'rebalance':args.rebalance,
        'top_pct':args.top_pct,'composite':{'method':'共同有效样本内百分位排名等权平均','weights':{k:0.2 for k in NAMES if k != 'MULTI'}},'n_stocks':len(securities),'execution':'前一交易日信号 / 次日开盘调仓',
        'model':'复权单位研究组合；不计费用、整手、冲击成本；开盘停牌/涨跌停约束；非真实成交回测',
        'benchmark':'沪深300价格指数（聚宽提供）；因子组合为复权收益，分红口径不同',
        'baseline_date':str(baseline.date()),'trade_start':str(bt[0].date()),'audit_dir':str(outdir),'research_factors':RESEARCH},
        'dates':[str(d.date()) for d in dates],'series':series}
    from factor_metrics import add_excess_metrics
    add_excess_metrics(result)
    dest = BASE/'factor_data_jq.json'
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    from refresh_factor_page import refresh
    refresh(dest)
    print('完成。行情、持仓、调仓和因子值已保存至',outdir)
    jq.logout()

if __name__ == '__main__':
    try: main()
    except KeyboardInterrupt: print('\n已取消；未替换页面数据。')
    except Exception as exc:
        print('未完成：',type(exc).__name__, str(exc))
        raise SystemExit(1)

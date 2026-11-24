"""Screen causal price signals across the cached historical CSI 300 universe."""
import csv
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from jqdata_local import BASE, select_stocks, simulate, stats
from factor_metrics import add_excess_metrics
from refresh_factor_page import refresh, validate


def candidates(prices):
    close = prices['close'].where(prices['close'].gt(0))
    open_price = prices['open'].where(prices['open'].gt(0))
    daily = close.pct_change(fill_method=None)
    for window in (5, 10, 20, 40, 60, 90, 120):
        momentum = close / close.shift(window) - 1
        yield f'MOM{window}', f'{window} 日动量', momentum, f'收盘价 ÷ {window} 日前收盘价 − 1'
        if window <= 40:
            yield f'REV{window}', f'{window} 日反转', -momentum, f'{window} 日动量取负'
        if window >= 20:
            for skip in (3, 5, 10):
                yield (f'GAP{window}_{skip}', f'{window} 日动量跳过近 {skip} 日',
                       close.shift(skip) / close.shift(window) - 1,
                       f'{skip} 日前收盘价 ÷ {window} 日前收盘价 − 1')
            volatility = daily.rolling(window).std()
            yield f'ADJ{window}', f'{window} 日风险调整动量', momentum / volatility, f'{window} 日动量 ÷ 同期日收益标准差'
    for window in (10, 20, 40, 60):
        for key, name, ratio, formula in (
            ('DAY', '日内强度', close / open_price, '复权收盘价 ÷ 当日复权开盘价'),
            ('NIGHT', '隔夜强度', open_price / close.shift(), '复权开盘价 ÷ 前日复权收盘价'),
        ):
            score = np.expm1(np.log(ratio).rolling(window).sum())
            yield f'{key}{window}', f'{window} 日{name}', score, f'最近 {window} 日（{formula}）连乘 − 1'
    for fast, slow, smooth in ((5, 15, 5), (8, 21, 5), (12, 26, 9), (19, 39, 9)):
        macd = close.ewm(span=fast, adjust=False, min_periods=fast).mean() - close.ewm(
            span=slow, adjust=False, min_periods=slow).mean()
        histogram = (macd - macd.ewm(span=smooth, adjust=False, min_periods=smooth).mean()) / close
        yield (f'MACD{fast}_{slow}_{smooth}', f'MACD 柱线 {fast}/{slow}/{smooth}', histogram.where(close.notna()),
               f'{fast}/{slow}/{smooth} 日 MACD 柱线 ÷ 收盘价')


def rank_blends(factors, signals, pools, paused):
    pairs = [
        ('MACD12_26_9', 'MOM60', 'MACD 与 60 日动量'),
        ('MACD12_26_9', 'GAP60_5', 'MACD 与跳过近 5 日动量'),
        ('MACD8_21_5', 'DAY20', '短周期 MACD 与日内强度'),
        ('MOM60', 'NIGHT20', '60 日动量与隔夜强度'),
        ('ADJ60', 'MACD12_26_9', '风险调整动量与 MACD'),
    ]
    for first, second, name in pairs:
        rows = {}
        for day, signal in signals.items():
            idx = pools[day]
            scores = pd.DataFrame({key: factors[key].loc[signal].reindex(idx) for key in (first, second)})
            scores = scores.replace([np.inf, -np.inf], np.nan).dropna()
            scores = scores.loc[paused.loc[signal].reindex(scores.index).eq(0)]
            rows[signal] = scores.rank(pct=True).mean(axis=1)
        yield f'BLEND_{first}_{second}', name, pd.DataFrame.from_dict(rows, orient='index'), f'{first} 与 {second} 截面百分位排名等权平均'


def metrics(nav, benchmark, split_index):
    relative = np.asarray(nav) / benchmark
    result = stats(nav)
    result.update({
        'annual_excess': float((relative[-1] ** (250 / (len(relative) - 1)) - 1) * 100),
        'early_excess': float((relative[split_index] ** (250 / split_index) - 1) * 100),
        'late_excess': float(((relative[-1] / relative[split_index]) ** (
            250 / (len(relative) - 1 - split_index)) - 1) * 100),
    })
    return result


def main():
    data = json.loads((BASE / 'factor_data.json').read_text())
    validate(data)
    audit = Path(data['meta']['audit_dir'])
    raw = pd.read_csv(audit / 'prices_adjusted.csv', parse_dates=['time'])
    prices = {field: raw.pivot(index='time', columns='code', values=field).sort_index()
              for field in ['open', 'close', 'paused', 'high_limit', 'low_limit']}
    history = json.loads((audit / 'universe.json').read_text())
    dates = pd.DatetimeIndex(data['dates'][1:])
    signals = {pd.Timestamp(day): pd.Timestamp(info['signal_date']) for day, info in history.items()}
    pools = {pd.Timestamp(day): info['stocks'] for day, info in history.items()}
    benchmark = np.array(next(s['values'] for s in data['series'] if s['key'] == 'BENCH'))
    split_index = len(dates) // 2
    results = []
    standalone = list(candidates(prices))
    factor_map = {key: score for key, _, score, _ in standalone}
    blends = list(rank_blends(factor_map, signals, pools, prices['paused']))
    factor_map.update({key: score for key, _, score, _ in blends})
    for key, name, score, formula in [*standalone, *blends]:
        for top in (0.02, 0.03, 0.05, 0.10, 0.20):
            picks, _ = select_stocks(score, prices, signals, pools, top, key)
            curve, _, _ = simulate(prices, picks, dates)
            nav = [1., *curve]
            results.append(dict(key=key, name=name, top=top, formula=formula, **metrics(nav, benchmark, split_index)))
    ranked = sorted(results, key=lambda r: r['annual_excess'], reverse=True)
    report = BASE / 'factor_mining_screen.csv'
    with report.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(ranked[0]))
        writer.writeheader()
        writer.writerows(ranked)

    # Keep the best prior concentration alongside the leading screened variants.
    reference = next(row for row in ranked if row['top'] >= .05)
    best = [ranked[0]]
    if reference != ranked[0]:
        best.append(reference)
    groups = {row['key'].split('_')[0].rstrip('0123456789') for row in best}
    for row in ranked:
        family = row['key'].split('_')[0].rstrip('0123456789')
        if family in groups:
            continue
        best.append(row)
        groups.add(family)
        if len(best) == 3:
            break

    old_research = {k: v for k, v in data['meta'].get('research_factors', {}).items() if not k.startswith('SCAN_')}
    series = [s for s in data['series'] if not s['key'].startswith('SCAN_')]
    definitions = {}
    records = {'trades': [], 'holdings': [], 'factor_snapshots': []}
    for row, color in zip(best, ['#f09a71', '#66bddd', '#b5aaec']):
        key = f"SCAN_{row['key']}_{round(row['top'] * 100)}"
        name = f"{row['name']} · 前{row['top']:.0%}"
        picks, snapshots = select_stocks(factor_map[row['key']], prices, signals, pools, row['top'], key)
        curve, trades, holdings = simulate(prices, picks, dates)
        nav = [1., *curve]
        series.insert(-1, {'key': key, 'name': name, 'values': nav, 'stats': stats(nav)})
        definitions[key] = {
            'name': name, 'color': color,
            'formula': f"{row['formula']}。选排名前 {row['top']:.0%} 等权。",
            'source': f"本轮历史筛选 · 全段年化超额 {row['annual_excess']:+.2f}% · 后半段 {row['late_excess']:+.2f}%",
        }
        records['trades'].extend([key, *entry] for entry in trades)
        records['holdings'].extend([key, *entry] for entry in holdings)
        records['factor_snapshots'].extend(snapshots)

    data['series'] = series
    data['meta']['research_factors'] = {**old_research, **definitions}
    previous_mining = data['meta'].get('mining', {})
    data['meta']['mining'] = {
        'signals': len(factor_map), 'trials': len(ranked), 'target': 100,
        'hits': sum(r['annual_excess'] >= 100 for r in ranked),
        'split': data['dates'][split_index], 'best': ranked[0], 'reference': reference,
    }
    if previous_mining.get('best') == ranked[0] and 'forward' in previous_mining:
        data['meta']['mining']['forward'] = previous_mining['forward']
    add_excess_metrics(data)
    validate(data)
    for name, rows in records.items():
        path = audit / f'{name}.csv'
        old = pd.read_csv(path)
        combined = pd.concat([old.loc[~old['factor'].str.startswith('SCAN_')],
                              pd.DataFrame(rows, columns=old.columns)], ignore_index=True)
        temp = path.with_suffix('.csv.tmp')
        combined.to_csv(temp, index=False)
        temp.replace(path)
    dest = BASE / 'factor_data_jq.json'
    temp = dest.with_suffix('.json.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))
    temp.replace(dest)
    refresh(dest)
    print(json.dumps(data['meta']['mining'], ensure_ascii=False))
    for row in best:
        print(row)


if __name__ == '__main__':
    main()

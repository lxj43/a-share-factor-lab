"""Rebuild the offline dashboards using seeded, fictional prices and securities."""
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd

from build_holdings_report import build_report
from factor_metrics import add_excess_metrics
from jqdata_local import NAMES, build_factors, select_stocks, simulate, stats
from research_factors import RESEARCH, build_research_factors

ROOT = Path(__file__).resolve().parent


def main():
    rng = np.random.default_rng(42)
    days = pd.bdate_range('2024-01-02', periods=160)
    codes = [f'DEMO{i:02}' for i in range(1, 13)]
    market = rng.normal(0.0003, 0.008, len(days))
    returns = market[:, None] + rng.normal(0, 0.012, (len(days), len(codes)))
    close = pd.DataFrame(25 * np.exp(returns.cumsum(axis=0)), index=days, columns=codes)
    opening = close.shift(1).fillna(close) * np.exp(rng.normal(0, 0.004, close.shape))
    prices = {
        'close': close, 'open': opening, 'paused': close * 0,
        'high_limit': opening * 1.10, 'low_limit': opening * 0.90,
    }
    baseline, trading = days[-81], days[-80:]
    signals = {day: days[days.get_loc(day) - 1] for day in trading[::20]}
    pools = dict.fromkeys(signals, codes)
    core = build_factors(prices)
    factors = {**core, 'MULTI': None, **build_research_factors(close)}
    audit = ROOT / 'data' / 'demo'
    audit.mkdir(parents=True, exist_ok=True)

    raw = pd.concat({name: frame.stack() for name, frame in prices.items()}, axis=1)
    raw.to_csv(audit / 'prices_adjusted.csv', index_label=['time', 'code'])
    series, holdings, trades, snapshots = [], [], [], []
    for key, factor in factors.items():
        picks, records = select_stocks(factor, prices, signals, pools, .25, key,
                                       core if key == 'MULTI' else None)
        curve, orders, positions = simulate(prices, picks, trading)
        values = [1.0] + curve
        name = RESEARCH[key]['name'] if key in RESEARCH else NAMES[key]
        series.append(dict(key=key, name=name, values=values, stats=stats(values)))
        trades.extend([key, *row] for row in orders)
        holdings.extend([key, *row] for row in positions)
        snapshots.extend(records)
    benchmark = np.exp(np.r_[0.0, market[-80:].cumsum()]).tolist()
    series.append(dict(key='BENCH', name='合成基准', values=benchmark, stats=stats(benchmark)))
    dates = [str(day.date()) for day in [baseline, *trading]]
    data = dict(
        dates=dates, series=series,
        meta=dict(source='合成数据 · 演示', provider='Synthetic', start=dates[0], end=dates[-1],
                  rebalance=20, top_pct=.25, n_stocks=len(codes), audit_dir='data/demo',
                  benchmark='合成基准', research_factors=RESEARCH, baseline_date=dates[0],
                  model='合成标的和行情，仅用于展示与测试'),
    )
    pd.DataFrame(trades, columns='factor date code side adjusted_units adjusted_price amount'.split()).to_csv(audit/'trades.csv', index=False)
    pd.DataFrame(holdings, columns='factor date code adjusted_units adjusted_price value'.split()).to_csv(audit/'holdings.csv', index=False)
    pd.DataFrame(snapshots, columns='factor signal_date execution_date code factor_value selected'.split()).to_csv(audit/'factor_snapshots.csv', index=False)
    add_excess_metrics(data)
    page = ROOT / 'factor_compare.html'
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace('</', '<\\/')
    html, count = re.subn(r'const DATA = .*?;\nconst C =', lambda _: f'const DATA = {payload};\nconst C =',
                          page.read_text(), count=1, flags=re.S)
    if count != 1:
        raise ValueError('看板数据占位缺失')
    page.write_text(html)
    (ROOT / 'factor_data.json').write_text(json.dumps(data, ensure_ascii=False, indent=2))
    build_report(data, base=ROOT)


if __name__ == '__main__':
    main()

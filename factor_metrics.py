"""Benchmark-relative metrics; all input NAVs must share dates and start at one."""
import numpy as np


def add_excess_metrics(data):
    benchmark = np.asarray(next(s['values'] for s in data['series'] if s['key']=='BENCH'), dtype=float)
    if len(benchmark)<2 or np.any(benchmark<=0):raise ValueError('Invalid benchmark NAV')
    metrics={}
    for series in data['series']:
        nav=np.asarray(series['values'],dtype=float)
        if len(nav)!=len(benchmark) or not np.isfinite(nav).all():raise ValueError('Unaligned NAV')
        ratio=nav/benchmark
        active=nav[1:]/nav[:-1]-benchmark[1:]/benchmark[:-1]
        sd=float(np.std(active,ddof=1)) if len(active)>1 else 0.
        metrics[series['key']]={
            'return_difference_pp':((nav-benchmark)*100).tolist(),
            'relative_nav':ratio.tolist(),
            'total_difference_pp':float((nav[-1]-benchmark[-1])*100),
            'relative_return_pct':float((ratio[-1]-1)*100),
            'annual_relative_return_pct':float((ratio[-1]**(250/(len(nav)-1))-1)*100),
            'relative_max_drawdown_pct':float(np.max(1-ratio/np.maximum.accumulate(ratio))*100),
            'annual_tracking_error_pct':sd*np.sqrt(250)*100,
            'information_ratio':float(np.mean(active)/sd*np.sqrt(250)) if sd>1e-14 else None,
        }
    data['excess']={'benchmark_key':'BENCH','annualization':250,
                    'difference_definition':'策略累计收益−基准累计收益，单位百分点',
                    'relative_definition':'策略净值÷基准净值−1',
                    'information_ratio_definition':'每日策略收益与基准收益之差的均值/样本标准差×sqrt(250)',
                    'series':metrics}
    return data

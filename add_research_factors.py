"""Recalculate the candidate factors from the existing JQData cache."""
import json
from pathlib import Path

import pandas as pd

from factor_metrics import add_excess_metrics
from jqdata_local import BASE, select_stocks, simulate, stats
from refresh_factor_page import refresh, validate
from research_factors import RESEARCH, build_research_factors


def main():
    data = json.loads((BASE / 'factor_data.json').read_text())
    validate(data)
    audit_dir = Path(data['meta']['audit_dir'])
    raw = pd.read_csv(audit_dir / 'prices_adjusted.csv', parse_dates=['time'])
    prices = {
        field: raw.pivot(index='time', columns='code', values=field).sort_index()
        for field in ['open', 'close', 'paused', 'high_limit', 'low_limit']
    }
    history = json.loads((audit_dir / 'universe.json').read_text())
    signals = {pd.Timestamp(day): pd.Timestamp(info['signal_date']) for day, info in history.items()}
    pools = {pd.Timestamp(day): info['stocks'] for day, info in history.items()}
    dates = pd.DatetimeIndex(data['dates'][1:])
    records = {'trades': [], 'holdings': [], 'factor_snapshots': []}
    series = []
    for key, factor in build_research_factors(prices['close']).items():
        picks, snapshots = select_stocks(
            factor, prices, signals, pools, data['meta']['top_pct'], key
        )
        curve, trades, holdings = simulate(prices, picks, dates)
        values = [1.] + curve
        series.append({'key': key, 'name': RESEARCH[key]['name'], 'values': values, 'stats': stats(values)})
        records['trades'].extend([key, *row] for row in trades)
        records['holdings'].extend([key, *row] for row in holdings)
        records['factor_snapshots'].extend(snapshots)

    baseline = [s for s in data['series'] if s['key'] not in RESEARCH and s['key'] != 'BENCH']
    benchmark = next(s for s in data['series'] if s['key'] == 'BENCH')
    data['series'] = [*baseline, *series, benchmark]
    data['meta']['research_factors'] = RESEARCH
    add_excess_metrics(data)
    validate(data)

    for name, rows in records.items():
        path = audit_dir / f'{name}.csv'
        previous = pd.read_csv(path)
        existing = previous.loc[~previous['factor'].isin(RESEARCH)]
        updated = pd.concat([existing, pd.DataFrame(rows, columns=previous.columns)], ignore_index=True)
        tmp = path.with_suffix('.csv.tmp')
        updated.to_csv(tmp, index=False)
        tmp.replace(path)
    dest = BASE / 'factor_data_jq.json'
    tmp = dest.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))
    tmp.replace(dest)
    refresh(dest)
    for candidate in series:
        relative = data['excess']['series'][candidate['key']]['relative_return_pct']
        print(candidate['name'], candidate['stats'], f'相对净值收益 {relative:+.2f}%')


if __name__ == '__main__':
    main()

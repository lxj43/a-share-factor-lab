#!/usr/bin/env python3
"""Validate JQData export and replace only data in the current dashboard."""
import argparse
import json
import math
import re
import shutil
from datetime import datetime
from pathlib import Path
BASE = Path(__file__).resolve().parent


def validate(data):
    if data.get('meta', {}).get('provider') != 'JQData':
        raise ValueError('只接受标明 provider=JQData 的新导出，拒绝将旧数据标成聚宽')
    dates = data['dates']
    if len(dates) < 2 or dates != sorted(set(dates)):
        raise ValueError('日期必须严格递增且不重复')
    for d in dates: datetime.strptime(d, '%Y-%m-%d')
    if data['meta']['start'] != dates[0] or data['meta']['end'] != dates[-1]:
        raise ValueError('区间与日期不一致')
    keys = [s['key'] for s in data['series']]
    if len(keys) != len(set(keys)) or 'BENCH' not in keys or len(keys) < 2:
        raise ValueError('因子或基准缺失/重复')
    for s in data['series']:
        values = s['values']
        if len(values) != len(dates) or abs(values[0]-1) > 1e-8:
            raise ValueError('净值长度或起点错误')
        if not all(isinstance(v, (int,float)) and math.isfinite(v) and v > 0 for v in values):
            raise ValueError('净值存在无效数值')
        if abs(s['stats']['total'] - (values[-1]-1)*100) > .011:
            raise ValueError('累计收益与净值不符')


def refresh(src):
    data = json.loads(Path(src).read_text())
    validate(data)
    audit_dir = data.get('meta', {}).get('audit_dir')
    if audit_dir and (Path(audit_dir)/'holdings.csv').exists() and (BASE/'factor_holdings_template.html').exists():
        from build_holdings_report import build_report
        build_report(data, base=BASE)
    page = BASE/'factor_compare.html'
    html = page.read_text()
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace('</', '<\\/')
    updated, n = re.subn(r'const DATA = .*?;\nconst C =', lambda _: 'const DATA = '+payload+';\nconst C =', html, count=1, flags=re.S)
    if n != 1: raise ValueError('找不到页面数据占位；未修改文件')
    # Preserve all layout and interactions. Back up before publishing either file.
    backup = BASE/'data'/'page_backups'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup.mkdir(parents=True)
    for p in [page, BASE/'factor_data.json']:
        if p.exists(): shutil.copy2(p, backup/p.name)
    temp = page.with_suffix('.html.tmp'); temp.write_text(updated); temp.replace(page)
    target = BASE/'factor_data.json'; temp = target.with_suffix('.json.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)); temp.replace(target)
    print('已更新聚宽数据并保留页面设计:',page)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', nargs='?', default=str(BASE/'factor_data_jq.json'))
    args = parser.parse_args()
    refresh(args.source)

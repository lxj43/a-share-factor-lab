#!/usr/bin/env python3
"""Loopback market and factor dashboard. No credential files are served."""
import argparse
import csv
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from time import time
import re
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
CN_TZ = timezone(timedelta(hours=8))
MARKETS = {
    '沪深市场': ['sh000001', 'sz399001', 'sh000300', 'sz399006', 'sh000688',
                  'sh600519', 'sh601318', 'sz300750', 'sz002594', 'sh600036',
                  'sh601398', 'sh601288', 'sh600900', 'sh600028', 'sh601857', 'sh601088',
                  'sh600276', 'sh601012', 'sh601899', 'sh600030', 'sh600941', 'sh603259',
                  'sz000333', 'sz000651', 'sz000858', 'sz300059', 'sz300124', 'sz002475',
                  'sz000001', 'sz002415', 'sz002230', 'sz000725'],
    '中证 800 行业': ['sh000928', 'sh000929', 'sh000930', 'sh000931', 'sh000932', 'sh000933',
                      'sh000974', 'sz399965', 'sh000935', 'sh000936', 'sh000937', 'sz399986'],
    '美国市场': ['us.INX', 'us.IXIC', 'us.DJI', 'usSPY', 'usQQQ', 'usAAPL',
                  'usMSFT', 'usNVDA', 'usAMZN', 'usGOOGL', 'usMETA', 'usTSLA',
                  'usAMD', 'usAVGO', 'usTSM', 'usASML', 'usINTC', 'usMU', 'usORCL', 'usCRM',
                  'usPLTR', 'usJPM', 'usGS', 'usV', 'usMA', 'usWMT', 'usCOST', 'usKO',
                  'usXOM', 'usCVX', 'usLLY', 'usUNH', 'usDIS', 'usNET', 'usIWM', 'usDIA'],
    '美国行业': ['usXLB', 'usXLC', 'usXLE', 'usXLF', 'usXLI', 'usXLK',
                  'usXLP', 'usXLRE', 'usXLU', 'usXLV', 'usXLY'],
}
DOMESTIC_INDICES = set(MARKETS['沪深市场'][:5] + MARKETS['中证 800 行业'])
EXTRA_MARKETS = {
    '大宗商品': {
        '101.GC00Y': ('COMEX 黄金期货', '美元/盎司'),
        '101.SI00Y': ('COMEX 白银期货', '美元/盎司'),
        '102.CL00Y': ('WTI 原油期货', '美元/桶'),
        '101.HG00Y': ('COMEX 铜期货', '美元/磅'),
    },
    '外汇市场': {
        '100.UDI': ('美元指数', '点'),
        '133.USDCNH': ('美元兑离岸人民币', 'CNH/USD'),
        'USDCNY': ('美元兑在岸人民币', 'CNY/USD'),
    }
}
EXTERNAL = {key: value for group in EXTRA_MARKETS.values() for key, value in group.items()}
SINA_FUTURES = {'101.GC00Y':'GC', '101.SI00Y':'SI', '102.CL00Y':'CL', '101.HG00Y':'HG'}
SINA_FX = {'133.USDCNH':'fx_susdcnh', 'USDCNY':'fx_susdcny'}
SPECIAL_BOARDS = {'BK1617': '黄金', 'BK1340': '印制电路板', 'BK0459': '电子元件'}

SECTORS = dict(zip(MARKETS['美国行业'],
                   ['原材料', '通信服务', '能源', '金融', '工业', '信息技术',
                    '必需消费', '房地产', '公用事业', '医疗保健', '可选消费']))
DOMESTIC = re.compile(r'(sh|sz)[0-9]{6}')
AMERICAN = re.compile(r'us[.A-Z][A-Z0-9.]{0,10}')
BOARD = re.compile(r'BK[0-9]{4}')
MARKET_LOGO = re.compile(r'/assets/market-logos/[A-Za-z0-9]+\.png')
AUDIT_CSV = re.compile(r'/data/(?:demo|jqdata_[0-9]{8}_[0-9]{8})/(?:trades|holdings)\.csv')
OVERVIEW_CACHE = ROOT / 'data' / 'market_overview_cache.json'
OVERVIEW_LOCK = Lock()
FILES = {
    '/': 'market_dashboard.html', '/market_dashboard.html': 'market_dashboard.html',
    '/factor_library.html': 'factor_library.html',
    '/market_intraday.js': 'market_intraday.js',
    '/market_charts.js': 'market_charts.js',
    '/market_dashboard.js': 'market_dashboard.js', '/market_dashboard.css': 'market_dashboard.css',
    '/dashboard_glass.css': 'dashboard_glass.css',
    '/dashboard_fonts.css': 'dashboard_fonts.css', '/factor_compare.html': 'factor_compare.html',
    '/factor_holdings.html': 'factor_holdings.html', '/factor_mining_screen.csv': 'factor_mining_screen.csv',
}
BASE_FORMULAS = {
    'REV5': '−(当日收盘价 ÷ 5 个交易日前收盘价 − 1)',
    'MOM20': '当日收盘价 ÷ 20 个交易日前收盘价 − 1',
    'MOM60': '当日收盘价 ÷ 60 个交易日前收盘价 − 1',
    'VOL60': '近 60 个交易日日收益率的样本标准差，取负值',
    'OVERNIGHT': '近 20 个交易日的（当日开盘价 ÷ 上一交易日收盘价）连乘，再减 1',
    'MULTI': '在共同有效股票池中，将 5 个基础因子的横截面百分位排名等权平均',
}
MIMES = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.csv': 'text/csv', '.png': 'image/png'}


def read_url(url):
    domain = urlsplit(url).hostname or ''
    headers = {'User-Agent': 'Mozilla/5.0'}
    if domain.endswith('.gtimg.cn'):
        headers['Referer'] = 'https://finance.qq.com/'
    elif domain.endswith('.eastmoney.com'):
        headers['Referer'] = 'https://quote.eastmoney.com/'
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=4) as response:
            return response.read(2_000_000)
    except OSError:
        with urlopen(req, timeout=6) as response:
            return response.read(2_000_000)


def get_json(base, **params):
    return json.loads(read_url(base + '?' + urlencode(params, safe=",")))


def number(value):
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def quote_fields(symbols):
    payload = read_url('https://qt.gtimg.cn/q=' + ','.join(symbols)).decode('gb18030', errors='replace')
    return {symbol: raw.split('~') for symbol, raw in re.findall(r'v_([A-Za-z0-9.]+)="([^"]*)"', payload)}


def quotes(symbols):
    result = {}
    for symbol, fields in quote_fields(symbols).items():
        if len(fields) < 36 or number(fields[3]) is None or number(fields[3]) <= 0:
            continue
        american = symbol.startswith('us')
        label = SECTORS.get(symbol, fields[1])
        stamp = fields[30]
        if re.fullmatch(r'\d{14}', stamp):
            stamp = datetime.strptime(stamp, '%Y%m%d%H%M%S').isoformat(sep=' ')
        result[symbol] = dict(id=symbol, name=label, code=fields[2], value=number(fields[3]),
                              percent=number(fields[32]), timestamp=stamp,
                              seriesType='index' if symbol in DOMESTIC_INDICES or symbol.startswith('us.') else 'security',
                              zone='纽约时间' if american else '北京时间', source='腾讯财经',
                              unit='USD' if american and not symbol.startswith('us.') else
                                   'CNY' if DOMESTIC.fullmatch(symbol) and symbol not in DOMESTIC_INDICES else '点')
    return result


def industry_page(page):
    data = get_json('https://push2.eastmoney.com/api/qt/clist/get',
                    pn=page, pz=100, po=1, np=1, fltt=2, fid='f3', fs='m:90+t:2',
                    fields='f12,f14,f2,f3,f124').get('data') or {}
    rows = []
    for item in data.get('diff') or []:
        if not BOARD.fullmatch(str(item.get('f12'))) or number(item.get('f3')) is None:
            continue
        epoch = number(item.get('f124'))
        rows.append(dict(id=item['f12'], code=item['f12'], name=item['f14'], value=number(item['f2']),
                         percent=number(item['f3']), unit='点', source='东方财富',
                         timestamp=datetime.fromtimestamp(epoch, CN_TZ).isoformat(sep=' ', timespec='seconds')[:19] if epoch else '',
                         zone='北京时间'))
    if not rows:
        raise ValueError('行业行情暂不可用')
    return rows, int(data.get('total') or len(rows))


@lru_cache(maxsize=8)
def overview(bucket):
    failures = {}
    try:
        symbols = list(dict.fromkeys(symbol for group in MARKETS.values() for symbol in group))
        quotes_by_symbol = quotes(symbols)
        if not quotes_by_symbol:
            raise ValueError('报价源未返回数据')
        groups = {name: [quotes_by_symbol[symbol] for symbol in members if symbol in quotes_by_symbol]
                  for name, members in MARKETS.items()}
    except (OSError, ValueError, KeyError) as exc:
        failures['市场报价'] = str(exc)
        try:
            previous = json.loads(OVERVIEW_CACHE.read_text())
        except (OSError, ValueError):
            previous = {}
        groups = previous.get('groups', {})

    result = {'groups': groups, 'failures': failures,
              'fetchedAt': datetime.now(CN_TZ).isoformat(timespec='seconds')}
    if not failures:
        OVERVIEW_CACHE.parent.mkdir(exist_ok=True)
        temporary = OVERVIEW_CACHE.with_suffix('.tmp')
        temporary.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False))
        temporary.replace(OVERVIEW_CACHE)
    return result


def board_history(symbol, limit):
    endpoint = '/api/qt/stock/kline/get?'
    params = dict(secid='90.' + symbol, klt=101, fqt=0, lmt=limit, end=20500101,
                  fields1='f1,f2,f3,f4,f5,f6', fields2='f51,f52,f53,f56')
    query = urlencode(params, safe=',')
    public_chart_query = urlencode(dict(params, cb='factorBoard', fqt=1, lmt=limit,
        ut='fa5fd1943c7b386f172d6893dbfba10b',
        fields2='f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61'))
    requests = (
        ('push2his.eastmoney.com', query, 3, False),
        ('7.push2his.eastmoney.com', query, 3, False),
        ('push2his.eastmoney.com', public_chart_query, 5, True),
    )
    for host, parameters, volume_index, jsonp in requests:
        address = f'https://{host}{endpoint}{parameters}'
        try:
            payload = subprocess.check_output(
                ['curl', '--fail', '--silent', '--compressed', '--max-time', '3',
                 '--referer', f'https://quote.eastmoney.com/bk/90.{symbol}.html', address],
                timeout=4).decode('utf-8-sig').strip()
            if jsonp:
                match = re.fullmatch(r'factorBoard\((.*)\);?', payload, flags=re.S)
                if not match:
                    continue
                payload = match.group(1)
            data = json.loads(payload).get('data') or {}
        except (OSError, subprocess.SubprocessError, ValueError):
            continue
        if data.get('code') == symbol and data.get('market') == 90 and data.get('klines'):
            rows = [line.split(',') for line in data['klines']]
            points = history_points(rows, close=2, volume=volume_index)
            if len(points) >= 2:
                return {'points': points[-limit:], 'source': '东方财富日线'}
    raise ValueError('东方财富板块日线暂不可用')


def history_points(rows, close, volume):
    points = []
    for row in rows:
        if len(row) <= close or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', row[0]):
            continue
        value = number(row[close])
        if value is not None and value > 0:
            points.append({'date': row[0], 'value': value,
                           'volume': number(row[volume]) if len(row) > volume else None})
    return points


def fetch_history(symbol, limit=30):
    if symbol in SINA_FUTURES or symbol in SINA_FX or symbol=='100.UDI':
        try:
            return sina_history(symbol,limit)
        except (OSError,ValueError,subprocess.SubprocessError):
            if symbol == 'USDCNY':
                raise
    if symbol in EXTERNAL:
        data = east_series('kline', symbol, klt=101, fqt=0, lmt=limit, end=20500101,
                           fields1='f1,f2,f3,f4,f5,f6', fields2='f51,f52,f53,f54,f55,f56')
        points = history_points([row.split(',') for row in data.get('klines', [])], 2, 5)
        if not points:
            raise ValueError('该标的暂无日线')
        return {'points': points, 'source': '东方财富日线'}
    if BOARD.fullmatch(symbol):
        return board_history(symbol, limit)
    american = symbol.startswith('us')
    effective = symbol
    if american and not symbol.startswith('us.'):
        quote = quotes([symbol]).get(symbol)
        if not quote:
            raise ValueError('未找到该美股代码')
        effective = 'us' + quote['code']
    if not (DOMESTIC.fullmatch(effective) or AMERICAN.fullmatch(effective)):
        raise ValueError('代码格式不支持')
    endpoint = 'usfqkline' if american else 'fqkline'
    data = get_json('https://web.ifzq.gtimg.cn/appstock/app/' + endpoint + '/get',
                    param=f'{effective},day,,,{limit},qfq').get('data') or {}
    ticker = data.get(effective, {})
    rows = ticker.get('qfqday') or ticker.get('day') or []
    points = history_points(rows, close=2, volume=5)
    if len(points) < 2:
        raise ValueError('该代码暂无日线')
    return {'points': points, 'source': '腾讯财经日线'}


def persisted_market_data(directory_name, key, load):
    directory = ROOT / 'data' / directory_name
    path = directory / f'{key}.json'
    try:
        result = load()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        if path.is_file():
            return dict(json.loads(path.read_text()), cached=True)
        raise
    directory.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode='w', dir=directory, encoding='utf-8', delete=False) as handle:
        json.dump(result, handle, ensure_ascii=False, allow_nan=False)
        temporary = Path(handle.name)
    temporary.replace(path)
    return result


def history(symbol, limit=30):
    key = symbol if limit == 30 else f'{symbol}_{limit}'
    try:
        return persisted_market_data('market_history', key, lambda: fetch_history(symbol, limit))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        previous = ROOT / 'data' / 'market_history' / f'{symbol}.json'
        if limit != 30 and previous.is_file():
            return dict(json.loads(previous.read_text()), cached=True)
        raise


def macro(days=370):
    start = (datetime.now(CN_TZ).date() - timedelta(days=days)).isoformat()
    address = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10&cosd=' + start
    try:
        payload = subprocess.check_output(
            ['curl', '--fail', '--silent', '--show-error', '--max-time', '10', address],
            timeout=12, stderr=subprocess.DEVNULL, text=True)
    except (OSError, subprocess.SubprocessError):
        payload = read_url(address).decode()
    points = [{'date': row['observation_date'], 'value': number(row['DGS10'])}
              for row in csv.DictReader(payload.splitlines()) if number(row['DGS10']) is not None]
    if not points:
        raise ValueError('FRED 暂无观察值')
    return {'source': 'FRED · DGS10', 'points': points}


def industry_snapshot(page):
    def load():
        rows, total = industry_page(page)
        return {'rows': rows, 'total': total, 'page': page}

    return persisted_market_data('market_industries', page, load)


def east_series(kind, secid, **params):
    query = urlencode(dict(secid=secid, **params), safe=',')
    hosts = ('push2his.eastmoney.com','7.push2his.eastmoney.com')
    if kind == 'trends2':
        hosts += ('push2.eastmoney.com',)
    for host in hosts:
        url = f'https://{host}/api/qt/stock/{kind}/get?{query}'
        try:
            body = subprocess.check_output(['curl','-fsS','--max-time','3',
                                            '--referer','https://quote.eastmoney.com/',url],
                                           stderr=subprocess.DEVNULL,timeout=4)
            item = json.loads(body).get('data') or {}
            if item.get('code') == secid.split('.')[1]:
                return item
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
    raise ValueError('东方财富行情暂不可用')


@lru_cache(maxsize=128)
def find_instruments(term, market, bucket):
    rows = []
    if market == 'board':
        raw = get_json('https://searchapi.eastmoney.com/api/suggest/get', input=term, type=14)
        for item in (raw.get('QuotationCodeTable') or {}).get('Data') or []:
            code = str(item.get('Code',''))
            if BOARD.fullmatch(code):
                rows.append({'id':code,'name':item['Name'],'code':code})
        return rows[:16]
    address = 'https://smartbox.gtimg.cn/s3/?' + urlencode(dict(q=term, t='all', v=2, c=1))
    raw = read_url(address).decode('gb18030', errors='replace')
    match = re.search(r'v_hint\s*=\s*"([^"]*)"',raw)
    if not match:
        return []
    seen = set()
    for row in match.group(1).split('^'):
        fields = row.split('~')
        if len(fields) < 5:
            continue
        exchange, code, name, _, kind = fields[:5]
        code = code.upper()
        name = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m[1],16)),name)
        symbol = exchange + (code.rsplit('.',1)[0] if exchange == 'us' else code)
        if market == 'china' and (not DOMESTIC.fullmatch(symbol) or kind != 'GP-A'):
            continue
        if market == 'usa' and not AMERICAN.fullmatch(symbol):
            continue
        if market == 'indices' and (kind != 'ZS' or not DOMESTIC.fullmatch(symbol)):
            continue
        if symbol not in seen:
            seen.add(symbol)
            rows.append({'id':symbol,'name':name,'code':code.split('.')[0]})
    return rows[:16]


def east_quote(symbol):
    if symbol in EXTERNAL:
        try:
            return sina_quote(symbol)
        except (OSError, ValueError, subprocess.SubprocessError):
            if symbol == 'USDCNY':
                raise
    external = EXTERNAL.get(symbol)
    secid = symbol if external else '90.' + symbol
    try:
        data = get_json('https://push2.eastmoney.com/api/qt/stock/get', secid=secid,
                        fields='f57,f58,f43,f59,f170,f86').get('data') or {}
    except OSError:
        if not BOARD.fullmatch(symbol):
            raise
        for path in (ROOT/'data'/'market_industries').glob('*.json'):
            entries = json.loads(path.read_text()).get('rows', [])
            cached = next((row for row in entries if row['id']==symbol), None)
            if cached:
                return dict(cached,cached=True)
        raise
    value, decimals = number(data.get('f43')), number(data.get('f59'))
    if value is None or decimals is None or data.get('f57') != secid.split('.')[1]:
        raise ValueError('该标的暂无报价')
    name, unit = external or (SPECIAL_BOARDS.get(symbol, data['f58']), '点')
    stamp = number(data.get('f86'))
    movement = number(data.get('f170'))
    return {'id':symbol, 'name':name, 'code':data['f57'], 'value':value/(10**decimals), 'unit':unit,
            'percent':None if movement is None else movement/100, 'source':'东方财富',
            'timestamp':datetime.fromtimestamp(stamp,CN_TZ).isoformat(sep=' ',timespec='seconds')[:19] if stamp else '',
            'zone':'北京时间'}


def latest_session(symbol):
    if symbol in SINA_FUTURES or symbol in SINA_FX:
        try:
            return sina_session(symbol)
        except (OSError, ValueError, subprocess.SubprocessError):
            if symbol == 'USDCNY':
                raise
    source = '腾讯财经分时'
    if BOARD.fullmatch(symbol) or symbol in EXTERNAL:
        secid = symbol if symbol in EXTERNAL else '90.' + symbol
        item = east_series('trends2',secid,fields1='f1,f2,f3,f4,f5,f6,f7,f8',
                           fields2='f51,f52,f53,f54,f55,f56,f57,f58', iscr=0, ndays=1)
        rows = [row.split(',') for row in item.get('trends',[])]
        ordered = [(row[0],number(row[2])) for row in rows if len(row)>2 and number(row[2]) is not None]
        if not ordered:
            raise ValueError('分时行情暂不可用')
        first_day = ordered[0][0][:10]
        close = '15:00' if BOARD.fullmatch(symbol) else '06:00'
        start = '09:30' if BOARD.fullmatch(symbol) else ordered[0][0][11:16]
        points = [{'time':stamp[11:16],'value':value} for stamp,value in ordered]
        return {'date':first_day,'points':points,'open':start,'close':close,'zone':'北京时间',
                'source':'东方财富分时','segments':[['11:30','13:00']] if BOARD.fullmatch(symbol) else [],
                'overnight':symbol in EXTERNAL and start>=close}
    american = symbol.startswith('us')
    effective = symbol
    if american and not symbol.startswith('us.'):
        quote = quotes([symbol]).get(symbol)
        if not quote:
            raise ValueError('未找到该美股代码')
        effective = 'us' + quote['code']
    endpoint = 'UsMinute' if american else 'minute'
    item = get_json('https://web.ifzq.gtimg.cn/appstock/app/' + endpoint + '/query',code=effective)
    data = ((item.get('data') or {}).get(effective) or {}).get('data') or {}
    date = data.get('date','')
    if not re.fullmatch(r'\d{8}',date):
        raise ValueError('分时行情暂不可用')
    date = datetime.strptime(date,'%Y%m%d').date().isoformat()
    points = []
    for row in data.get('data',[]):
        cells = row.split()
        if len(cells)>1 and re.fullmatch(r'\d{4}',cells[0]) and number(cells[1]) is not None:
            points.append({'time':cells[0][:2]+':'+cells[0][2:],'value':number(cells[1])})
    if not points:
        raise ValueError('分时行情暂不可用')
    close = '16:00' if american else '15:00'
    if american and date < datetime.now(ZoneInfo('America/New_York')).date().isoformat() and points[-1]['time'] == '13:00':
        close = '13:00'
    return {'date':date,'points':points,'open':'09:30','close':close,'source':source,
            'zone':'纽约时间' if american else '北京时间','segments':[] if american else [['11:30','13:00']]}


@lru_cache(maxsize=160)
def intraday(symbol, bucket):
    return persisted_market_data('market_intraday', symbol, lambda: latest_session(symbol))


def fetch_sina(url):
    return subprocess.check_output(['curl','-fsSL','--max-time','5',
                                    '--referer','https://finance.sina.com.cn/',url],
                                   stderr=subprocess.DEVNULL,timeout=6)


def sina_chart(method, pool, **params):
    domains = {
        'futures': 'https://stock2.finance.sina.com.cn/futures/api/jsonp.php/printed/GlobalFuturesService.',
        'fx': 'https://vip.stock.finance.sina.com.cn/forex/api/jsonp.php/printed/NewForexService.',
    }
    script = fetch_sina(domains[pool]+method+'?'+urlencode(params)).decode()
    response = re.search(r'printed\((.*)\);?\s*$',script,re.S)
    return json.loads(response.group(1)) if response else None


def sina_quote(symbol):
    future = SINA_FUTURES.get(symbol)
    code = 'hf_'+future if future else SINA_FX.get(symbol,'DINIW')
    payload = fetch_sina('https://hq.sinajs.cn/list='+code).decode('gb18030',errors='replace')
    match = re.search(r'hq_str_'+code+r'="([^"]+)"',payload)
    fields = match.group(1).split(',') if match else []
    minimum = 13 if future else 10 if code=='DINIW' else 18
    if len(fields) < minimum:
        raise ValueError('新浪财经报价暂不可用')
    if future:
        value, previous, date, clock = number(fields[0]),number(fields[7]),fields[12],fields[6]
    else:
        value, previous, date, clock = number(fields[8]),number(fields[3]),fields[-1],fields[0]
    if value is None:
        raise ValueError('新浪财经报价暂不可用')
    if future == 'HG':
        value /= 100
        previous = previous/100 if previous is not None else None
    name, unit = EXTERNAL[symbol]
    return {'id':symbol,'name':name,'unit':unit,'code':future or code.removeprefix('fx_s').upper(),
            'value':value,'percent':100*(value/previous-1) if previous else None,
            'timestamp':date+' '+clock,'zone':'北京时间','source':'新浪财经'}


def sina_history(symbol,limit):
    future = SINA_FUTURES.get(symbol)
    if future:
        data = sina_chart('getGlobalFuturesDailyKLine','futures',symbol=future)
        factor = .01 if future=='HG' else 1
        if not isinstance(data,list):
            raise ValueError('新浪财经日线暂不可用')
        points = [{'date':row['date'],'value':number(row['close'])*factor,'volume':number(row.get('volume'))}
                  for row in data[-limit:] if number(row.get('close'))]
    else:
        data = sina_chart('getDayKline','fx',symbol=SINA_FX.get(symbol,'DINIW'))
        if not isinstance(data,str):
            raise ValueError('新浪财经日线暂不可用')
        points = history_points([row.split(',') for row in data.split('|')[-limit:]],4,5)
    if not points:
        raise ValueError('新浪财经日线暂不可用')
    return {'points':points,'source':'新浪财经日线'}


def sina_session(symbol):
    future = SINA_FUTURES.get(symbol)
    if future:
        response = sina_chart('getGlobalFuturesMinLine','futures',symbol=future)
        rows = response.get('minLine_1d',[]) if isinstance(response,dict) else []
        if not rows or len(rows[0])<6:
            raise ValueError('新浪财经期货分时暂不可用')
        header = rows[0]
        day, start = header[0],header[4]
        factor = .01 if future=='HG' else 1
        points = [{'time':time,'value':float(value)*factor} for time,value in
                  [(start,header[5])]+[(row[0],row[1]) for row in rows[1:] if len(row)>1]
                  if re.fullmatch(r'\d{2}:\d{2}',time) and number(value) is not None]
        # Daily maintenance break starts one hour before the next electronic session.
        close = (datetime.strptime(start,'%H:%M')-timedelta(hours=1)).strftime('%H:%M')
    else:
        rows = sina_chart('getMinKline','fx',symbol=SINA_FX[symbol],scale=5,datalen=300)
        if not isinstance(rows,list) or not rows:
            raise ValueError('新浪财经外汇分时暂不可用')
        start,close = ('09:30','03:00') if symbol=='USDCNY' else ('06:00','06:00')
        newest = datetime.strptime(rows[-1]['d'],'%Y-%m-%d %H:%M:%S')
        open_at = datetime.strptime(newest.date().isoformat()+' '+start,'%Y-%m-%d %H:%M')
        if newest < open_at:
            open_at -= timedelta(days=1)
        day = open_at.date().isoformat()
        points = [{'time':row['d'][11:16],'value':number(row['c'])}
                  for row in rows if row['d']>=open_at.isoformat(sep=' ',timespec='seconds')
                  and number(row['c']) is not None]
    if not points:
        raise ValueError('新浪财经分时暂不可用')
    overnight = start >= close
    # If the scheduled span elapsed and the provider delivered a shorter completed session,
    # retain the observed end rather than projecting an empty tail to the normal close.
    scheduled_close = datetime.strptime(day+' '+close,'%Y-%m-%d %H:%M').replace(tzinfo=CN_TZ)
    if overnight:
        scheduled_close += timedelta(days=1)
    if datetime.now(CN_TZ) > scheduled_close+timedelta(minutes=15):
        last = points[-1]['time']
        close,overnight = last,last < start
    return {'date':day,'open':start,'close':close,'overnight':overnight,'zone':'北京时间',
            'source':'新浪财经分时','segments':[],'points':points}


def valuation(symbol):
    fields = quote_fields([symbol]).get(symbol, [])
    if len(fields) < 47 or number(fields[3]) is None:
        raise ValueError('无该股票估值快照')
    return {'source': '腾讯财经估值快照', 'pe': number(fields[39]), 'pb': number(fields[46]),
            'turnover': number(fields[38]), 'marketCapBillions': number(fields[45])}


def factor_catalog():
    path = ROOT / 'factor_data.json'
    dashboard = json.loads((path if path.is_file() else ROOT / 'demo_factor_data.json').read_text())
    screen_path = ROOT / 'factor_mining_screen.csv'
    screening = []
    if dashboard['meta'].get('provider') != 'Synthetic' and screen_path.is_file():
        with screen_path.open(encoding='utf-8-sig', newline='') as stream:
            screening = list(csv.DictReader(stream))
    metrics = dashboard.get('excess', {}).get('series', {})
    published = []
    for item in dashboard['series']:
        key = item['key']
        if key == 'BENCH':
            continue
        definition = dashboard['meta'].get('research_factors', {}).get(key, {})
        published.append(dict(key=key, name=item['name'], formula=definition.get('formula', BASE_FORMULAS.get(key, '')),
                              source=definition.get('source', dashboard['meta']['source']),
                              total=item['stats']['total'], mdd=item['stats']['mdd'],
                              annual_excess=metrics.get(key, {}).get('annual_relative_return_pct')))
    return {'published': published, 'screening': screening, 'source': dashboard['meta']['source'], 'period': [
        dashboard['meta']['start'], dashboard['meta']['end']]}


class Handler(BaseHTTPRequestHandler):
    def send_payload(self, status, kind, body):
        self.send_response(status)
        self.send_header('Content-Type', kind if kind.startswith('image/') else kind + '; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def json(self, data, status=200):
        self.send_payload(status, 'application/json', json.dumps(data, ensure_ascii=False, allow_nan=False).encode())

    def do_GET(self):
        request = urlsplit(self.path)
        route = request.path
        filename = FILES.get(route)
        if AUDIT_CSV.fullmatch(route) or MARKET_LOGO.fullmatch(route):
            filename = route[1:]
        if filename:
            path = ROOT / filename
            if path.is_file():
                self.send_payload(200, MIMES[path.suffix], path.read_bytes())
                return
        query = parse_qs(request.query)
        symbol = query.get('symbol', [''])[0]
        valid_symbol = bool(DOMESTIC.fullmatch(symbol) or AMERICAN.fullmatch(symbol))
        supported_symbol = valid_symbol or BOARD.fullmatch(symbol) or symbol in EXTERNAL
        try:
            if route == '/api/overview':
                with OVERVIEW_LOCK:
                    result = overview(int(time()) // 30)
                self.json(result)
            elif route == '/api/industries':
                page = int(query.get('page', ['1'])[0])
                if not 1 <= page <= 20:
                    raise ValueError('页码超出范围')
                self.json(industry_snapshot(page))
            elif route == '/api/quote' and valid_symbol:
                entry = quotes([symbol]).get(symbol)
                self.json(entry if entry else {'error':'报价源没有返回该代码'}, 200 if entry else 404)
            elif route == '/api/quote' and supported_symbol:
                self.json(persisted_market_data('market_external_quotes', symbol, lambda: east_quote(symbol)))
            elif route == '/api/search':
                term = query.get('q',[''])[0].strip()
                market = query.get('market',[''])[0]
                if not 1 <= len(term) <= 32 or market not in ('china','usa','indices','board'):
                    self.json({'error':'无效的标的搜索'}, 400)
                else:
                    self.json({'rows':find_instruments(term,market,int(time())//300)})
            elif route == '/api/intraday' and supported_symbol:
                self.json(intraday(symbol, int(time())//60))
            elif route == '/api/history' and supported_symbol:
                limit = int(query.get('limit', ['30'])[0])
                if limit not in (30, 270):
                    raise ValueError('日线数量不支持')
                self.json(history(symbol, limit))
            elif route == '/api/valuation' and DOMESTIC.fullmatch(symbol) and symbol not in DOMESTIC_INDICES:
                self.json(valuation(symbol))
            elif route == '/api/factors':
                self.json(factor_catalog())
            elif route == '/api/macro':
                self.json(persisted_market_data('market_history', 'DGS10_370', macro))
            else:
                self.json({'error':'该页面或代码不存在'}, 404)
        except (OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError) as exc:
            self.json({'error': '数据请求未完成', 'detail': str(exc)}, 502)

    def log_message(self, *_):
        pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8769)
    args = parser.parse_args()
    with ThreadingHTTPServer(('127.0.0.1', args.port), Handler) as server:
        print(f'http://127.0.0.1:{args.port}/', flush=True)
        server.serve_forever()

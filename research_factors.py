"""Price-only research candidates based on the supplied ML for Trading notebooks."""
import numpy as np

RESEARCH = {
    "BBREV21": {
        "name": "布林带反转",
        "formula": "负的 21 日收盘价 Z 分数：−(收盘价 − 21 日均价) ÷ 21 日总体标准差。偏离下轨方向的股票得分更高。",
        "source": "02_how_to_use_talib.ipynb · BBANDS，转为反向选股分数",
        "color": "#e991a3",
    },
    "RSIREV14": {
        "name": "RSI 反转",
        "formula": "100 − RSI。RSI 用最近 14 日平均上涨与平均下跌幅度计算，采用简单滚动均值。",
        "source": "02_how_to_use_talib.ipynb · RSI，此处采用简单均值版本",
        "color": "#a89be9",
    },
    "MACDH": {
        "name": "MACD 柱线动量",
        "formula": "［12 日 EMA − 26 日 EMA − 其 9 日 EMA］÷ 收盘价。使用 pandas EMA，按归一化柱线从高到低排序。",
        "source": "02_how_to_use_talib.ipynb · MACD，增加价格归一化",
        "color": "#6eb7ce",
    },
    "MOM605": {
        "name": "跳过近 5 日动量",
        "formula": "5 个交易日前收盘价 ÷ 60 个交易日前收盘价 − 1，剔除最近 5 日价格变动。",
        "source": "01_feature_engineering.ipynb · 动量构造思路，改用日频窗口",
        "color": "#85cf9e",
    },
}


def build_research_factors(close):
    close = close.where(close.gt(0))
    rolling = close.rolling(21)
    bollinger = (rolling.mean() - close) / rolling.std(ddof=0).replace(0, np.nan)
    move = close.diff()
    gain = move.clip(lower=0).rolling(14).mean()
    loss = (-move.clip(upper=0)).rolling(14).mean()
    rsi_reversal = 100 * loss / (gain + loss).replace(0, np.nan)
    macd = close.ewm(span=12, adjust=False, min_periods=12).mean() - close.ewm(
        span=26, adjust=False, min_periods=26
    ).mean()
    histogram = (macd - macd.ewm(span=9, adjust=False, min_periods=9).mean()) / close
    return {
        "BBREV21": bollinger,
        "RSIREV14": rsi_reversal,
        "MACDH": histogram.where(close.notna()),
        "MOM605": close.shift(5) / close.shift(60) - 1,
    }

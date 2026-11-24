# A 股因子研究看板 v1.0

离线交互看板，用于比较单因子、等权多因子与基准表现。可切换净值和相对表现，查询调仓、成交与逐日持仓。

## 打开演示

直接打开 `factor_compare.html`，从「持仓变化」进入明细。演示使用固定随机种子生成的虚构证券和价格。

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python generate_demo.py
python -m unittest test_jqdata_local
```

## 使用自己有权访问的行情

安装 `requirements-jqdata.txt`，复制 `jqdata_credentials.example.json` 为本机的 `jqdata_credentials.json`，填写聚宽账号并保存在本机。用 `python jqdata_local.py --help` 查看区间、调仓周期和选股比例参数。计算脚本使用当时的沪深 300 历史成分股及前一交易日信号，在下一交易日开盘调仓。回测采用复权单位，考虑开盘停牌和涨跌停，不计费用与整手限制。

运行真实数据流程会在当前工作副本更新看板，并生成个人行情和交易明细。分享演示时使用重新生成的合成样本。

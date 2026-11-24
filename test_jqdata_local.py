import json
import tempfile
import unittest
from pathlib import Path
import pandas as pd
from jqdata_local import simulate
import refresh_factor_page as refresh_module

class ResearchPipelineTests(unittest.TestCase):
    def prices(self):
        self.days = pd.date_range('2026-01-05', periods=3, freq='B')
        close = pd.DataFrame([[10,10],[20,10],[20,20]],index=self.days,columns=['A','B'])
        return {'open':close.copy(),'close':close,'paused':close*0,'high_limit':close*1.1,'low_limit':close*.9}

    def test_hold_units_and_include_all_days(self):
        px = self.prices()
        curve,trades,_ = simulate(px,{self.days[0]:['A','B']},self.days)
        self.assertEqual(curve,[1,1.5,2])
        self.assertEqual(len(trades),2)

    def test_rebalance_on_open_and_cash_conservation(self):
        px = self.prices()
        curve,trades,holdings = simulate(px,{self.days[0]:['A','B'],self.days[1]:['B']},self.days)
        self.assertEqual(curve,[1,1.5,3])
        self.assertEqual(len(trades),4)
        self.assertAlmostEqual(sum(r[-1] for r in holdings if r[0]==str(self.days[-1].date())),300000)

    def test_blocked_buy_leaves_cash(self):
        px=self.prices();px['paused'].loc[self.days[0],'B']=1
        curve,_,_=simulate(px,{self.days[0]:['A','B']},self.days)
        self.assertEqual(curve,[1,1.5,1.5])

    def test_refresh_preserves_design_and_rejects_legacy(self):
        original_base=refresh_module.BASE
        with tempfile.TemporaryDirectory() as d:
            refresh_module.BASE=Path(d)
            html='<style>KEEP DESIGN</style>\nconst DATA = {};\nconst C = {};'
            (Path(d)/'factor_compare.html').write_text(html)
            result={'meta':{'provider':'JQData','start':'2026-01-01','end':'2026-01-02'},'dates':['2026-01-01','2026-01-02'],'series':[{'key':k,'values':[1,1.1],'stats':{'total':10}} for k in ['MOM20','BENCH']]}
            src=Path(d)/'jq.json';src.write_text(json.dumps(result))
            try:
                refresh_module.refresh(src)
                self.assertIn('<style>KEEP DESIGN</style>',(Path(d)/'factor_compare.html').read_text())
                result['meta']['provider']='Tencent';src.write_text(json.dumps(result))
                with self.assertRaises(ValueError):refresh_module.refresh(src)
            finally:refresh_module.BASE=original_base

if __name__=='__main__':unittest.main()

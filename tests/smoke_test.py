"""Runs the analytics on demo data (no network, no streamlit): python tests/smoke_test.py"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from core.demo import demo_cpi, demo_ppi, demo_pce
from core import analytics as A

for ds in (demo_cpi("2026-09-01"), demo_ppi("2026-09-01"), demo_pce("2026-08-01")):
    for tgt in ds.specs:
        for lvl in ds.specs[tgt]:
            df, act, res = A.contributions(ds, tgt, lvl)
            assert res.abs().max() < 0.2, (ds.name, tgt, lvl, res.abs().max())
    for v in ds.views:
        assert len(A.release_table(ds, v)) > 5
    assert A.diffusion(ds.idx, ds.diffusion_keys).dropna().shape[0] > 12
    print(ds.name, "ok")

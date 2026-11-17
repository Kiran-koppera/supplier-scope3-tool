from pathlib import Path

import pandas as pd
import pytest

from scope3.calculate import (METHOD_AVERAGE, METHOD_SPEND, METHOD_SUPPLIER,
                              calculate, load_inputs, summarise)
from scope3.scenarios import ScenarioConfig, engaged_mask, run_scenarios

ROOT = Path(__file__).resolve().parents[1]

FACTORS = pd.DataFrame([
    {"category": "Aluminium", "ghg_category": "Cat 1", "spend_factor_kgco2e_per_usd": 1.0,
     "activity_factor_kgco2e_per_kg": 10.0, "renewable_electricity_reducible_share": 0.5},
    {"category": "Services", "ghg_category": "Cat 1", "spend_factor_kgco2e_per_usd": 0.1,
     "activity_factor_kgco2e_per_kg": None, "renewable_electricity_reducible_share": 0.5},
])


def supplier(**kw):
    row = {"supplier_id": "S1", "supplier_name": "A", "country": "DE", "category": "Aluminium",
           "spend_usd": 1000, "quantity_kg": None, "supplier_pcf_kgco2e_per_kg": None,
           "pcf_third_party_verified": "no", "has_sbti_target": "no",
           "renewable_electricity_share": 0.0}
    row.update(kw)
    return row


def test_hierarchy_picks_most_specific_method():
    df = calculate(pd.DataFrame([
        supplier(supplier_id="PCF", quantity_kg=100, supplier_pcf_kgco2e_per_kg=4,
                 pcf_third_party_verified="yes"),
        supplier(supplier_id="AVG", quantity_kg=100),
        supplier(supplier_id="SPEND", category="Services"),
    ]), FACTORS).set_index("supplier_id")

    assert df.loc["PCF", "method"] == METHOD_SUPPLIER
    assert df.loc["PCF", "tco2e"] == pytest.approx(0.4)      # 100 kg * 4 / 1000
    assert df.loc["PCF", "dq_score"] == 1
    assert df.loc["AVG", "method"] == METHOD_AVERAGE
    assert df.loc["AVG", "tco2e"] == pytest.approx(1.0)      # 100 kg * 10 / 1000
    assert df.loc["SPEND", "method"] == METHOD_SPEND
    assert df.loc["SPEND", "tco2e"] == pytest.approx(0.1)    # 1000 USD * 0.1 / 1000
    assert df.loc["SPEND", "dq_score"] == 4


def test_unknown_category_raises():
    with pytest.raises(ValueError, match="no emission factor"):
        calculate(pd.DataFrame([supplier(category="Unicorns")]), FACTORS)


def test_shares_sum_to_one_and_summary_consistent():
    s, f = load_inputs(ROOT / "data" / "suppliers.csv", ROOT / "data" / "emission_factors.csv")
    df = calculate(s, f)
    assert df["share"].sum() == pytest.approx(1.0)
    assert df["cumulative_share"].iloc[-1] == pytest.approx(1.0)
    summary = summarise(df)
    assert summary["total_tco2e"] == pytest.approx(df["tco2e"].sum())
    assert 0 < summary["primary_data_coverage"] < 1
    assert 1 <= summary["weighted_dq_score"] <= 4


def test_scenarios_never_exceed_bau_and_start_at_base():
    s, f = load_inputs(ROOT / "data" / "suppliers.csv", ROOT / "data" / "emission_factors.csv")
    df = calculate(s, f)
    traj = run_scenarios(df, ScenarioConfig())
    first = traj.iloc[0]
    for col in ["bau", "renewable_electricity", "low_carbon_materials", "combined"]:
        assert first[col] == pytest.approx(df["tco2e"].sum())
    for col in ["renewable_electricity", "low_carbon_materials", "supplier_targets", "combined"]:
        assert (traj[col] <= traj["bau"] + 1e-9).all()
    assert traj["combined"].iloc[-1] < traj["bau"].iloc[-1]


def test_engaged_mask_reaches_coverage():
    s, f = load_inputs(ROOT / "data" / "suppliers.csv", ROOT / "data" / "emission_factors.csv")
    df = calculate(s, f)
    mask = engaged_mask(df, 0.8)
    assert df.loc[mask, "share"].sum() >= 0.8
    assert df.loc[mask, "share"].sum() - df.loc[mask, "share"].iloc[-1] < 0.8


def test_build_writes_outputs_and_injects_dashboard_data(tmp_path):
    import json

    from scope3.__main__ import build

    results = build(ROOT / "data" / "suppliers.csv", ROOT / "data" / "emission_factors.csv",
                    tmp_path, ScenarioConfig())
    for name in ["results.json", "dashboard.html", "supplier_emissions.csv",
                 "category_emissions.csv", "scenarios.csv", "engagement_list.csv"]:
        assert (tmp_path / name).exists(), name
    html = (tmp_path / "dashboard.html").read_text()
    assert "/*__DATA__*/" not in html            # placeholder was replaced
    assert html.startswith("<!doctype html>") and "width=device-width" in html
    assert json.loads((tmp_path / "results.json").read_text())["summary"] == results["summary"]
    assert results["config"]["target_adoption_year"] == 2027

"""Command line entry point.

    python -m scope3                      # uses the sample data in data/
    python -m scope3 --suppliers my.csv   # your own supplier spend extract
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .calculate import by_category, calculate, load_inputs, summarise
from .scenarios import ScenarioConfig, engagement_list, engaged_mask, run_scenarios

ROOT = Path(__file__).resolve().parents[1]
SUPPLIER_COLS = ["supplier_id", "supplier_name", "country", "category", "ghg_category",
                 "spend_usd", "tco2e", "spend_based_tco2e", "method", "dq_score",
                 "intensity_kgco2e_per_usd", "share", "cumulative_share",
                 "has_sbti_target", "renewable_electricity_share"]


def build(suppliers_csv: Path, factors_csv: Path, out_dir: Path, cfg: ScenarioConfig) -> dict:
    suppliers, factors = load_inputs(suppliers_csv, factors_csv)
    df = calculate(suppliers, factors)
    cats = by_category(df)
    traj = run_scenarios(df, cfg)
    engage = engagement_list(df)

    out_dir.mkdir(parents=True, exist_ok=True)
    df[SUPPLIER_COLS].to_csv(out_dir / "supplier_emissions.csv", index=False)
    cats.to_csv(out_dir / "category_emissions.csv", index=False)
    traj.to_csv(out_dir / "scenarios.csv", index=False)
    engage[["supplier_id", "supplier_name", "category", "tco2e", "dq_score",
            "has_sbti_target", "priority_score", "recommended_actions"]].to_csv(
        out_dir / "engagement_list.csv", index=False)

    results = {
        "summary": summarise(df),
        "config": {"base_year": cfg.base_year, "target_year": cfg.target_year,
                   "business_growth": cfg.business_growth,
                   "engagement_coverage": cfg.engagement_coverage,
                   "supplier_target_rate": cfg.supplier_target_rate,
                   "target_adoption_year": cfg.target_adoption_year,
                   "material_switch": {k: list(v) for k, v in cfg.material_switch.items()},
                   "suppliers_engaged": int(engaged_mask(df, cfg.engagement_coverage).sum())},
        "categories": cats.to_dict(orient="records"),
        "reducible": dict(zip(factors["category"],
                              factors["renewable_electricity_reducible_share"])),
        "suppliers": df[SUPPLIER_COLS].to_dict(orient="records"),
        "scenarios": traj.to_dict(orient="records"),
        "engagement": engage[["supplier_id", "supplier_name", "category", "tco2e", "share",
                              "dq_score", "has_sbti_target", "recommended_actions"]
                             ].to_dict(orient="records"),
    }
    (out_dir / "results.json").write_text(json.dumps(results, indent=2))

    template = (ROOT / "dashboard" / "template.html").read_text()
    body = template.replace("/*__DATA__*/null", json.dumps(results))
    # Wrap as a complete document so it renders correctly on any host and on phones.
    html = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            '</head>\n<body>\n' + body + '\n</body>\n</html>\n')
    (out_dir / "dashboard.html").write_text(html, encoding="utf-8")
    return results


def main() -> None:
    p = argparse.ArgumentParser(description="Supplier Scope 3 hotspot & reduction tool")
    p.add_argument("--suppliers", type=Path, default=ROOT / "data" / "suppliers.csv")
    p.add_argument("--factors", type=Path, default=ROOT / "data" / "emission_factors.csv")
    p.add_argument("--out", type=Path, default=ROOT / "output")
    p.add_argument("--growth", type=float, default=0.02, help="annual business growth")
    p.add_argument("--coverage", type=float, default=0.80,
                   help="engage suppliers covering this share of emissions")
    a = p.parse_args()
    if not 0 < a.coverage <= 1:
        p.error("--coverage must be between 0 and 1, e.g. 0.8 for 80%")
    if not -0.5 < a.growth < 1:
        p.error("--growth is a yearly fraction, e.g. 0.02 for 2%")

    r = build(a.suppliers, a.factors, a.out,
              ScenarioConfig(business_growth=a.growth, engagement_coverage=a.coverage))
    s = r["summary"]
    last = r["scenarios"][-1]
    print(f"Total upstream footprint : {s['total_tco2e']:,.0f} tCO2e "
          f"(+/- {s['uncertainty_tco2e']:,.0f})")
    print(f"Spend-based only would be: {s['spend_based_total_tco2e']:,.0f} tCO2e")
    print(f"Suppliers covering 80%   : {s['suppliers_for_80pct']} of {s['n_suppliers']}")
    print(f"Primary data coverage    : {s['primary_data_coverage']:.0%}  "
          f"(weighted DQ {s['weighted_dq_score']:.1f})")
    print(f"{last['year']} combined pathway : {last['combined']:,.0f} vs 1.5C target "
          f"{last['target_1p5c']:,.0f} tCO2e")
    print(f"Outputs written to {a.out}")


if __name__ == "__main__":
    main()

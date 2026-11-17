"""Reduction scenarios and supplier engagement prioritisation.

Levers are applied per supplier and per year, multiplicatively, so they never
double count the same tonne:

* Renewable electricity - engaged suppliers ramp linearly to 100% renewable
  power by the target year. Only the electricity-related share of the
  category footprint (``renewable_electricity_reducible_share``) can be cut,
  and only the part not already renewable.
* Low-carbon materials - recycled aluminium and EAF steel replace part of the
  conventional volume.
* Supplier targets - suppliers with a science-based target cut 4.2%/yr;
  engaged suppliers without one adopt a target from ``target_adoption_year``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

LINEAR_1P5C_RATE = 0.042  # absolute contraction per year, 1.5 degC aligned


@dataclass
class ScenarioConfig:
    base_year: int = 2025
    target_year: int = 2030
    business_growth: float = 0.02          # annual growth in purchased volumes
    engagement_coverage: float = 0.80      # engage suppliers covering this share of emissions
    supplier_target_rate: float = LINEAR_1P5C_RATE
    target_adoption_year: int = 2027
    # category -> (share of volume switched by target year, emission cut on switched volume)
    material_switch: dict = field(default_factory=lambda: {
        "Aluminium": (0.50, 1 - 1.5 / 14.0),          # primary -> recycled
        "Steel wire & products": (0.50, 1 - 0.7 / 2.0),  # BF-BOF -> EAF
    })


def engaged_mask(df: pd.DataFrame, coverage: float) -> pd.Series:
    """Largest emitters until ``coverage`` of the total is reached (df sorted desc)."""
    return (df["cumulative_share"] - df["share"]) < coverage


def _ramp(year: int, start: int, end: int) -> float:
    if year <= start:
        return 0.0
    return min(1.0, (year - start) / (end - start))


def run_scenarios(df: pd.DataFrame, cfg: ScenarioConfig | None = None) -> pd.DataFrame:
    """Yearly trajectory (tCO2e) for BAU, each lever and the combined pathway."""
    cfg = cfg or ScenarioConfig()
    engaged = engaged_mask(df, cfg.engagement_coverage)
    base = df["tco2e"]
    re_cut = df["renewable_electricity_reducible_share"] * (1 - df["renewable_electricity_share"])
    mat_share = df["category"].map(lambda c: cfg.material_switch.get(c, (0, 0))[0])
    mat_cut = df["category"].map(lambda c: cfg.material_switch.get(c, (0, 0))[1])

    rows = []
    base_total = float(base.sum())
    for year in range(cfg.base_year, cfg.target_year + 1):
        t = year - cfg.base_year
        growth = (1 + cfg.business_growth) ** t
        ramp = _ramp(year, cfg.base_year, cfg.target_year)

        f_re = 1 - re_cut * ramp * engaged
        f_mat = 1 - mat_share * mat_cut * ramp
        years_with_target = pd.Series(
            [t if sbti else (max(0, year - cfg.target_adoption_year) if eng else 0)
             for sbti, eng in zip(df["has_sbti_target"], engaged)], index=df.index)
        f_tgt = (1 - cfg.supplier_target_rate) ** years_with_target

        bau = base * growth
        rows.append({
            "year": year,
            "bau": float(bau.sum()),
            "renewable_electricity": float((bau * f_re).sum()),
            "low_carbon_materials": float((bau * f_mat).sum()),
            "supplier_targets": float((bau * f_tgt).sum()),
            # targets overlap with RE / materials, so take the larger cut per supplier
            "combined": float((bau * pd.concat([f_re * f_mat, f_tgt], axis=1).min(axis=1)).sum()),
            "target_1p5c": base_total * max(0.0, 1 - LINEAR_1P5C_RATE * t),
        })
    return pd.DataFrame(rows)


def engagement_list(df: pd.DataFrame, top_n: int = 12) -> pd.DataFrame:
    """Rank suppliers by impact x uncertainty x lack of a target, with next actions."""
    score = df["share"] * (df["dq_score"] / 3) * df["has_sbti_target"].map({True: 0.5, False: 1.0})
    out = df.assign(priority_score=score).sort_values("priority_score", ascending=False).head(top_n)

    def actions(r) -> str:
        a = []
        if r["dq_score"] >= 3:
            a.append("Request product carbon footprint (PACT format)")
        elif r["dq_score"] == 2:
            a.append("Ask for third-party PCF verification")
        if not r["has_sbti_target"]:
            a.append("Ask to set a science-based target")
        if r["renewable_electricity_share"] < 1:
            a.append(f"Renewable power plan (now {r['renewable_electricity_share']:.0%})")
        return "; ".join(a) or "Maintain; track annually"

    out["recommended_actions"] = out.apply(actions, axis=1)
    return out.reset_index(drop=True)

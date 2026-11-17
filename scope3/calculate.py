"""Supplier-level Scope 3 emissions using the GHG Protocol calculation hierarchy.

For every supplier line the most specific method available is used:

1. Supplier-specific  quantity_kg x supplier PCF (kgCO2e/kg)       DQ 1 (verified) / 2
2. Average-data       quantity_kg x industry-average factor         DQ 3
3. Spend-based        spend_usd   x EEIO factor (kgCO2e/USD)        DQ 4

DQ is a 1 (best) - 5 (worst) data quality score. Each score carries an
indicative uncertainty used to put a range around the total.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

METHOD_SUPPLIER = "Supplier-specific"
METHOD_AVERAGE = "Average-data"
METHOD_SPEND = "Spend-based"

# Indicative +/- uncertainty (1 sigma, as share of the estimate) for each DQ score.
DQ_UNCERTAINTY = {1: 0.10, 2: 0.20, 3: 0.30, 4: 0.50, 5: 0.60}

REQUIRED_SUPPLIER_COLS = {"supplier_id", "supplier_name", "country", "category", "spend_usd"}


def load_inputs(suppliers_csv: Path, factors_csv: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    suppliers = pd.read_csv(suppliers_csv)
    factors = pd.read_csv(factors_csv)
    missing = REQUIRED_SUPPLIER_COLS - set(suppliers.columns)
    if missing:
        raise ValueError(f"suppliers file is missing columns: {sorted(missing)}")
    for col, default in [("quantity_kg", np.nan), ("supplier_pcf_kgco2e_per_kg", np.nan),
                         ("pcf_third_party_verified", "no"), ("has_sbti_target", "no"),
                         ("renewable_electricity_share", 0.0)]:
        if col not in suppliers.columns:
            suppliers[col] = default
    return suppliers, factors


def calculate(suppliers: pd.DataFrame, factors: pd.DataFrame) -> pd.DataFrame:
    """Return one row per supplier with emissions, method, DQ score and uncertainty."""
    unknown = set(suppliers["category"]) - set(factors["category"])
    if unknown:
        raise ValueError(f"no emission factor for categories: {sorted(unknown)}")

    df = suppliers.merge(factors, on="category", how="left", validate="many_to_one")
    qty = pd.to_numeric(df["quantity_kg"], errors="coerce")
    pcf = pd.to_numeric(df["supplier_pcf_kgco2e_per_kg"], errors="coerce")
    act = pd.to_numeric(df["activity_factor_kgco2e_per_kg"], errors="coerce")
    verified = df["pcf_third_party_verified"].astype(str).str.lower().eq("yes")

    use_supplier = qty.notna() & pcf.notna()
    use_average = ~use_supplier & qty.notna() & act.notna()

    df["spend_based_tco2e"] = df["spend_usd"] * df["spend_factor_kgco2e_per_usd"] / 1000
    df["tco2e"] = np.select(
        [use_supplier, use_average],
        [qty * pcf / 1000, qty * act / 1000],
        default=df["spend_based_tco2e"],
    )
    df["method"] = np.select([use_supplier, use_average],
                             [METHOD_SUPPLIER, METHOD_AVERAGE], default=METHOD_SPEND)
    df["dq_score"] = np.select([use_supplier & verified, use_supplier, use_average],
                               [1, 2, 3], default=4).astype(int)
    df["uncertainty_tco2e"] = df["tco2e"] * df["dq_score"].map(DQ_UNCERTAINTY)
    df["intensity_kgco2e_per_usd"] = df["tco2e"] * 1000 / df["spend_usd"]
    df["has_sbti_target"] = df["has_sbti_target"].astype(str).str.lower().eq("yes")
    df["renewable_electricity_share"] = pd.to_numeric(
        df["renewable_electricity_share"], errors="coerce").fillna(0.0).clip(0, 1)

    df = df.sort_values("tco2e", ascending=False).reset_index(drop=True)
    total = df["tco2e"].sum()
    df["share"] = df["tco2e"] / total
    df["cumulative_share"] = df["share"].cumsum()
    return df


def summarise(df: pd.DataFrame) -> dict:
    total = float(df["tco2e"].sum())
    # Independent errors -> root-sum-square of supplier uncertainties.
    sigma = float(np.sqrt((df["uncertainty_tco2e"] ** 2).sum()))
    by_method = df.groupby("method")["tco2e"].sum()
    primary = float(by_method.get(METHOD_SUPPLIER, 0.0))
    n_80 = int((df["cumulative_share"] < 0.8).sum() + 1)
    return {
        "total_tco2e": total,
        "uncertainty_tco2e": sigma,
        "total_spend_usd": float(df["spend_usd"].sum()),
        "spend_based_total_tco2e": float(df["spend_based_tco2e"].sum()),
        "n_suppliers": int(len(df)),
        "suppliers_for_80pct": n_80,
        "primary_data_coverage": primary / total if total else 0.0,
        "weighted_dq_score": float((df["dq_score"] * df["tco2e"]).sum() / total) if total else 0.0,
        "sbti_coverage": float(df.loc[df["has_sbti_target"], "tco2e"].sum() / total) if total else 0.0,
    }


def by_category(df: pd.DataFrame) -> pd.DataFrame:
    out = (df.groupby(["category", "ghg_category"], as_index=False)
             .agg(tco2e=("tco2e", "sum"), spend_usd=("spend_usd", "sum"),
                  suppliers=("supplier_id", "count")))
    out["intensity_kgco2e_per_usd"] = out["tco2e"] * 1000 / out["spend_usd"]
    out["share"] = out["tco2e"] / out["tco2e"].sum()
    return out.sort_values("tco2e", ascending=False).reset_index(drop=True)

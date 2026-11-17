"""Generate a reproducible, fictional supplier spend dataset.

The dataset mimics the procurement profile of an optical fibre & cable plant:
glass precursors and gases, coatings and jacket polymers, strength members,
metals, packaging, logistics and services. All supplier names are fictional.

Run:  python scripts/generate_sample_data.py
"""
from __future__ import annotations

import csv
import random
from pathlib import Path

SEED = 42
OUT = Path(__file__).resolve().parents[1] / "data" / "suppliers.csv"

# category -> (number of suppliers, spend range USD, USD per kg if a physical good, share reporting a PCF)
PROFILE = {
    "Industrial gases & precursors": (5, (0.8e6, 6.5e6), None, 0.4),
    "Plastics & resins": (7, (0.5e6, 5.0e6), 2.6, 0.3),
    "Aramid & synthetic yarns": (3, (0.6e6, 3.5e6), 28.0, 0.34),
    "Steel wire & products": (4, (0.3e6, 2.2e6), 1.9, 0.25),
    "Aluminium": (2, (0.4e6, 1.8e6), 3.1, 0.5),
    "Copper": (2, (0.2e6, 1.0e6), 9.5, 0.0),
    "Packaging & reels": (5, (0.15e6, 1.4e6), 1.2, 0.2),
    "Electronic components": (3, (0.1e6, 0.9e6), None, 0.0),
    "Other chemicals": (4, (0.1e6, 1.1e6), None, 0.0),
    "Machinery & equipment": (3, (0.4e6, 3.0e6), None, 0.0),
    "Freight & logistics": (4, (0.3e6, 2.5e6), None, 0.0),
    "Professional & IT services": (4, (0.1e6, 1.2e6), None, 0.0),
}

COUNTRIES = ["DE", "PL", "CN", "US", "FR", "IT", "NL", "JP", "TR", "CZ", "IN", "KR"]
PREFIX = ["Nord", "Vista", "Helix", "Arcon", "Lumen", "Kestrel", "Brava", "Orbis", "Tessel",
          "Quarz", "Meridian", "Polar", "Sintra", "Velo", "Cobalt", "Ferro", "Alta", "Rhein"]
SUFFIX = {"Industrial gases & precursors": "Gases", "Plastics & resins": "Polymers",
          "Aramid & synthetic yarns": "Fibres", "Steel wire & products": "Wire",
          "Aluminium": "Metals", "Copper": "Cuprum", "Packaging & reels": "Pack",
          "Electronic components": "Electronics", "Other chemicals": "Chemie",
          "Machinery & equipment": "Maschinenbau", "Freight & logistics": "Logistics",
          "Professional & IT services": "Consulting"}

# Default emission factors (kgCO2e/kg) used to make supplier PCFs plausible:
# leaders report below the industry average, laggards above.
ACTIVITY_AVG = {"Plastics & resins": 2.10, "Aramid & synthetic yarns": 22.0,
                "Steel wire & products": 2.00, "Aluminium": 14.0, "Packaging & reels": 0.90}


def main() -> None:
    rng = random.Random(SEED)
    rows = []
    used = set()
    n = 1
    for cat, (count, (lo, hi), usd_per_kg, pcf_share) in PROFILE.items():
        for _ in range(count):
            while True:
                name = f"{rng.choice(PREFIX)} {SUFFIX[cat]}"
                if name not in used:
                    used.add(name)
                    break
            # log-uniform spend gives a realistic long tail
            spend = round(lo * (hi / lo) ** rng.random(), -3)
            qty = round(spend / (usd_per_kg * rng.uniform(0.85, 1.15))) if usd_per_kg else ""
            sbti = rng.random() < 0.35
            re_share = round(rng.choice([0, 0, 0.1, 0.25, 0.4, 0.6, 1.0]) if not sbti
                             else rng.choice([0.4, 0.6, 0.8, 1.0]), 2)
            pcf = ""
            verified = ""
            if qty and cat in ACTIVITY_AVG and rng.random() < pcf_share:
                pcf = round(ACTIVITY_AVG[cat] * rng.uniform(0.55, 1.1), 2)
                verified = "yes" if rng.random() < 0.5 else "no"
            rows.append({
                "supplier_id": f"S{n:03d}",
                "supplier_name": name,
                "country": rng.choice(COUNTRIES),
                "category": cat,
                "spend_usd": int(spend),
                "quantity_kg": qty,
                "supplier_pcf_kgco2e_per_kg": pcf,
                "pcf_third_party_verified": verified,
                "has_sbti_target": "yes" if sbti else "no",
                "renewable_electricity_share": re_share,
            })
            n += 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} suppliers to {OUT}")


if __name__ == "__main__":
    main()

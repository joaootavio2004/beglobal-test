#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compute a simple Attractiveness Index for a single country CSV from Be Global.
Usage:
  python be_global_index.py --csv "Be Global - Grupo 4(Market Analyzes).csv" [--bench be_global_benchmarks.json] [--weights be_global_weights.json]

Notes:
- This "simple" scorer uses only the categories that dominated calibration on R1:
  ECONÔMICO (PIB, PIB per capita, Crescimento do PIB) and INFRA/REG (Ease, Estradas, Regulação).
- Each feature is normalized with MIN-MAX using the provided benchmarks file.
- Final score = 100 × ( w_econ*econ_index + w_infra*infra_index ), where the two
  sub-indices are the average of their normalized features.
- Benchmarks/weights can be recalibrated later with more countries.
"""
import argparse, json, re
import pandas as pd
import numpy as np

def read_csv_safely(p):
    for enc in ["utf-8","latin-1","cp1252"]:
        for sep in [",",";"]:
            try:
                return pd.read_csv(p, encoding=enc, sep=sep)
            except Exception:
                continue
    raise RuntimeError(f"Falha ao ler {p}")

def detect_country(df):
    rows = df[df["Unnamed: 0"].astype(str).str.contains("Selecione o país", case=False, na=False)]
    if rows.empty:
        raise RuntimeError("Não encontrei o bloco do país (linha 'Selecione o país').")
    country = str(rows.iloc[0]["Unnamed: 2"])
    start = rows.index[0]
    next_rows = df.index[(df["Unnamed: 0"]=="Selecione o país") & (df.index>start)]
    end = next_rows[0] if len(next_rows)>0 else len(df)
    block = df.loc[start:end].reset_index(drop=True)
    return country, block

def get_val(block, patt):
    row = block[block["Unnamed: 0"].astype(str).str.contains(patt, case=False, na=False)]
    if row.empty:
        return None
    return row.iloc[0,2]

def to_number(x):
    if x is None or (isinstance(x,float) and np.isnan(x)): return np.nan
    s = str(x).strip()
    s = s.replace("$","").replace("%","").replace(",","")
    try:
        return float(re.sub(r"[^\d\.\-]", "", s))
    except Exception:
        return np.nan

def minmax_norm(val, vmin, vmax):
    if np.isnan(val) or vmin==vmax:
        return 0.0
    return max(0.0, min(1.0, (val - vmin)/(vmax - vmin)))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="Caminho do CSV do país (formato Be Global)")
    ap.add_argument("--bench", default="be_global_benchmarks.json", help="JSON com min/max por feature")
    ap.add_argument("--weights", default="be_global_weights.json", help="JSON com pesos por categoria")
    args = ap.parse_args()

    df = read_csv_safely(args.csv)
    country, block = detect_country(df)

    with open(args.bench) as f:
        bench = json.load(f)
    with open(args.weights) as f:
        weights = json.load(f)

    # features
    econ_feats = {
        "PIB (US$ bi)": get_val(block, "Produto Interno Bruto"),
        "PIB per capita (US$)": get_val(block, "PIB per capita"),
        "Crescimento PIB (%)": get_val(block, "Crescimento do PIB"),
    }
    infra_feats = {
        "Ease Doing Business": get_val(block, "facilidade de fazer negócios"),
        "Qualidade estradas": get_val(block, "estradas"),
        "Regulação (7=melhor)": get_val(block, "regulamentação"),
    }

    # normalize
    econ_norm = []
    for k,v in econ_feats.items():
        x = to_number(v)
        b = bench.get(k, None)
        if b is None:
            econ_norm.append(0.0)
        else:
            econ_norm.append( minmax_norm(x, b["min"], b["max"]) )
    infra_norm = []
    for k,v in infra_feats.items():
        x = to_number(v)
        b = bench.get(k, None)
        if b is None:
            infra_norm.append(0.0)
        else:
            infra_norm.append( minmax_norm(x, b["min"], b["max"]) )

    econ_idx = float(np.mean(econ_norm)) if econ_norm else 0.0
    infra_idx = float(np.mean(infra_norm)) if infra_norm else 0.0

    w_econ = float(weights.get("Econômico", 0.7))
    w_infra = float(weights.get("Infra/Reg", 0.3))

    score01 = w_econ*econ_idx + w_infra*infra_idx
    score100 = 100.0*score01

    print("País:", country)
    print("Índice Econômico (0–1):", round(econ_idx,4))
    print("Índice Infra/Reg (0–1):", round(infra_idx,4))
    print("Pesos → Econômico:", w_econ, "| Infra/Reg:", w_infra)
    print("ÍNDICE DE ATRATIVIDADE (0–100):", round(score100,2))

if __name__ == "__main__":
    main()

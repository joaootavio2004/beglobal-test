#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Be Global — Decision Helper (v0.3.5)
------------------------------------
Correções/importante:
- Price override para países JA PRESENTES agora casa por nome canônico (normalizado) e respeita --lock_price_owned.
- Coluna "AppliedOverride" para você confirmar que o override foi aplicado.
- Dedup confiável de países já presentes (case-insensitive).
- Mesma base da v0.3.3 (demanda/pop, objetivo blended, target_share, k_owned, pmax_owned_mult etc.).
"""

import argparse, re, math, warnings
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", message="Unknown extension is not supported and will be removed")
warnings.filterwarnings("ignore", message="Conditional Formatting extension is not supported and will be removed")
warnings.filterwarnings("ignore", message="Data Validation extension is not supported and will be removed")

# ------------------------
# Utils
# ------------------------
def read_xls(xlsx_path: str):
    return pd.ExcelFile(xlsx_path)

def read_sheet(xls, name: str, header=None) -> pd.DataFrame:
    return pd.read_excel(xls, sheet_name=name, header=header)

def _strip_accents(s: str) -> str:
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))

def normalize_country(name: str) -> str:
    if not isinstance(name, str):
        name = str(name)
    s = _strip_accents(name).lower().strip()
    synonyms = {
        "estados unidos": "united states",
        "eua": "united states",
        "united states of america": "united states",
        "reino unido": "united kingdom",
        "uk": "united kingdom",
        "inglaterra": "united kingdom",
        "alemanha": "germany",
        "japao": "japan",
        "coreia do sul": "south korea",
        "korea, rep.": "south korea",
        "republic of korea": "south korea",
        "russian federation": "russia",
        "viet nam": "vietnam",
        "czech republic": "czechia",
        "u.a.e.": "united arab emirates",
    }
    return synonyms.get(s, s)

def normalize_region_pt_to_mse(pt_region: str) -> Optional[str]:
    if not isinstance(pt_region, str):
        return None
    s = _strip_accents(pt_region).lower().strip()
    mapping = {
        "asia-pacifico": "Asia & Pacific",
        "asia pacifico": "Asia & Pacific",
        "asia & pacifico": "Asia & Pacific",
        "asia": "Asia & Pacific",
        "america do norte": "North America",
        "america do sul": "South America",
        "america central": "Central America",
        "uniao europeia": "European Union",
        "europa": "Europe",
        "oriente medio": "Middle East",
        "africa subsaariana": "Sub-Saharan Africa",
        "caribe": "The Caribbean",
        "oceania": "Oceania",
    }
    return mapping.get(s, None)

# ------------------------
# Long-table extraction
# ------------------------
import re as _re

def detect_year_header_row(xls, sheet: str, max_rows: int = 6) -> int:
    df = pd.read_excel(xls, sheet_name=sheet, header=None)
    yr_re = _re.compile(r"(?:19|20)\d{2}")
    best_row, best_hits = 0, -1
    for r in range(min(max_rows, df.shape[0])):
        hits = int(df.iloc[r,:].astype(str).str.contains(yr_re).sum())
        if hits > best_hits:
            best_row, best_hits = r, hits
    return best_row

def _robust_to_numeric(x):
    if pd.isna(x):
        return np.nan
    s = str(x).strip().replace("\xa0"," ")
    v = pd.to_numeric(s, errors="coerce")
    if pd.notna(v):
        return v
    s2 = s.replace(" ", "")
    if "," in s2 and s2.count(",")==1 and s2.rsplit(",",1)[1].isdigit():
        s3 = s2.replace(".", "").replace(",", ".")
        v = pd.to_numeric(s3, errors="coerce")
        if pd.notna(v):
            return v
    s4 = _re.sub(r"[^0-9eE+\-\.]", "", s2)
    return pd.to_numeric(s4, errors="coerce")

def extract_year_long_table(xls, sheet: str, country_col: Optional[str], year_header_row: Optional[int], value_label: str, min_year: int = 2008) -> pd.DataFrame:
    df = pd.read_excel(xls, sheet_name=sheet, header=None if year_header_row is not None else 0)
    if year_header_row is not None:
        header = df.iloc[year_header_row,:].tolist()
        ccol = None
        lower = [str(v).strip().lower() for v in header]
        if country_col and country_col.strip().lower() in lower:
            ccol = lower.index(country_col.strip().lower())
        if ccol is None:
            for j,v in enumerate(lower):
                if v in {"name","country name","country"} or ("name" in v) or ("country" in v):
                    ccol = j; break
        if ccol is None:
            ccol = 0
        year_map = {}
        for j, v in enumerate(header):
            m = _re.search(r"(?:19|20)\d{2}", str(v))
            if m:
                y = int(m.group(0))
                if y >= min_year:
                    year_map[j] = y
        rows = []
        for i in range(year_header_row+1, df.shape[0]):
            cname = str(df.iat[i, ccol]).strip()
            if not cname or cname.lower() in {"country","name","world","region","nan","none"}:
                continue
            for j, y in year_map.items():
                val = _robust_to_numeric(df.iat[i,j])
                if pd.notna(val):
                    rows.append({"Country": cname, "Year": int(y), value_label: float(val)})
        return pd.DataFrame(rows)
    else:
        df.columns = [str(c).strip() for c in df.columns]
        if country_col and country_col in df.columns:
            ccol = country_col
        else:
            ccol = None
            lower_cols = [c.lower() for c in df.columns]
            for target in ["name","country name","country"]:
                if target in lower_cols:
                    ccol = df.columns[lower_cols.index(target)]; break
            if ccol is None:
                for c in df.columns:
                    if ("name" in c.lower()) or ("country" in c.lower()):
                        ccol = c; break
            if ccol is None:
                ccol = df.columns[0]
        year_cols = []
        for c in df.columns:
            m = _re.search(r"(?:19|20)\d{2}", str(c))
            if m:
                y = int(m.group(0))
                if y >= min_year:
                    year_cols.append((c, y))
        rows = []
        for _, r in df.iterrows():
            cname = str(r[ccol]).strip()
            if not cname or cname.lower() in {"country","name","world","region","nan","none"}:
                continue
            for c, y in year_cols:
                val = _robust_to_numeric(r.get(c, None))
                if pd.notna(val):
                    rows.append({"Country": cname, "Year": int(y), value_label: float(val)})
        return pd.DataFrame(rows)

def build_macro_with_units(xls, pop_sheet: str, country_col: str, year_header_row: int,
                           gdp_year_header_row: Optional[int] = None, gdp_auto: bool = False, gdp_country_col: Optional[str] = None,
                           min_year: int = 2008, debug: bool=False) -> pd.DataFrame:
    pop = extract_year_long_table(xls, pop_sheet, country_col, year_header_row, "Population", min_year=min_year)
    gdp_hdr = detect_year_header_row(xls, "GDP") if gdp_auto else (gdp_year_header_row if gdp_year_header_row is not None else year_header_row)
    gdp_col = gdp_country_col if gdp_country_col is not None else country_col
    gdp = extract_year_long_table(xls, "GDP", gdp_col, gdp_hdr, "GDP", min_year=min_year)

    pop = pop.copy(); gdp = gdp.copy()
    pop["NormCountry"] = pop["Country"].map(normalize_country)
    gdp["NormCountry"] = gdp["Country"].map(normalize_country)
    df = pd.merge(pop.rename(columns={"Country":"PopCountry"}),
                  gdp.rename(columns={"Country":"GdpCountry"}),
                  on=["NormCountry","Year"], how="left")
    df = df.rename(columns={"PopCountry":"Country"})

    # Fix population sign & auto-scale
    df["Population"] = pd.to_numeric(df["Population"], errors="coerce")
    df.loc[df["Population"]<0, "Population"] = df.loc[df["Population"]<0, "Population"].abs()

    def _safe_percentile(s, q):
        s2 = pd.to_numeric(s, errors="coerce")
        s2 = s2[np.isfinite(s2)]
        return float(np.percentile(s2, q)) if len(s2)>0 else np.nan

    p95_pop = _safe_percentile(df["Population"], 95)
    pop_scale = 1.0
    if np.isfinite(p95_pop):
        if p95_pop < 2:        pop_scale = 1e9
        elif p95_pop < 2000:   pop_scale = 1e6
        elif p95_pop < 2e6:    pop_scale = 1e3
    df["Population"] = df["Population"] * pop_scale

    df["GDP"] = pd.to_numeric(df["GDP"], errors="coerce")
    gdppc_raw = df["GDP"] / df["Population"]
    med_raw = float(gdppc_raw[gdppc_raw>0].median(skipna=True)) if gdppc_raw.notna().any() else np.nan
    gdp_scale = 1.0
    if np.isfinite(med_raw) and med_raw>0:
        target = 10000.0
        guess = target / med_raw
        choices = [1.0, 1e3, 1e6, 1e9, 1e12]
        gdp_scale = min(choices, key=lambda z: abs(z - guess))
    df["GDP"] = df["GDP"] * gdp_scale
    df["GDPpc"] = df["GDP"] / df["Population"]
    if debug:
        print(f"[debug] unit scales → pop_scale={pop_scale:g}, gdp_scale={gdp_scale:g}")
        for probe in ["United States","Canada","China","India","Germany"]:
            sub = df[df["Country"].str.lower()==probe.lower()].sort_values("Year")
            if not sub.empty:
                y = int(sub["Year"].iloc[-1]); g = sub["GDP"].iloc[-1]; p = sub["Population"].iloc[-1]; pc = sub["GDPpc"].iloc[-1]
                print(f"[debug] sample {probe} last-year~{y}: GDP={g:.3g}, Pop={p:.3g}, GDPpc={pc:.3g}")
    return df

# ------------------------
# Demand extractor
# ------------------------
def extract_demand_table(xls, sheet="Market Analyzes") -> pd.DataFrame:
    try:
        df = pd.read_excel(xls, sheet_name=sheet, header=0)
    except Exception:
        return pd.DataFrame(columns=["Country","Demand"])
    df.columns = [str(c).strip() for c in df.columns]
    ccol = None
    for c in df.columns:
        cl = c.lower()
        if cl in {"country","name","country name"} or "country" in cl or "name" in cl:
            ccol = c; break
    if ccol is None:
        ccol = df.columns[0]
    dcol = None
    for c in df.columns:
        cl = c.lower()
        if any(k in cl for k in ["demand","demanda","market demand","market size","demanda de mercado","tamanho do mercado"]):
            dcol = c; break
    if dcol is None:
        num_cols = []
        for c in df.columns[1:]:
            v = pd.to_numeric(df[c], errors="coerce")
            if v.notna().sum() > 0:
                num_cols.append((c, float(v.median(skipna=True))))
        num_cols.sort(key=lambda x: x[1], reverse=True)
        dcol = num_cols[0][0] if num_cols else None
    if dcol is None:
        return pd.DataFrame(columns=["Country","Demand"])
    out = df[[ccol, dcol]].copy()
    out.columns = ["Country","Demand"]
    out["Country"] = out["Country"].astype(str).str.strip()
    out["Demand"] = pd.to_numeric(out["Demand"], errors="coerce")
    out = out.dropna(subset=["Country","Demand"])
    out["NormCountry"] = out["Country"].map(normalize_country)
    out = out.sort_values("Demand", ascending=False).drop_duplicates("NormCountry")
    return out[["NormCountry","Demand"]]

# ------------------------
# Result data helpers
# ------------------------
def get_empresa_columns(rd: pd.DataFrame, empresa_num: int) -> Dict[int, int]:
    header_rows = rd.index[rd.iloc[:,0].astype(str).str.contains(r"Financial", case=False, na=False)].tolist()
    if not header_rows:
        raise RuntimeError("Linha 'Financial' não encontrada em 'Result data'.")
    header_row = header_rows[0]
    mapping = {}
    for j in range(1, rd.shape[1]):
        v = rd.iat[header_row, j]
        if isinstance(v, str) and re.match(fr"Empresa_{empresa_num}_\d{{4}}", v):
            year = int(v.rsplit("_",1)[1])
            mapping[year] = j
    if not mapping:
        raise RuntimeError(f"Colunas Empresa_{empresa_num}_YYYY não encontradas em 'Result data'.")
    return mapping

def read_metric_value_for_year(rd: pd.DataFrame, group: int, label_regex: str, year: int) -> Optional[float]:
    cols = get_empresa_columns(rd, group)
    years = sorted(cols.keys())
    y = year if year in years else max([t for t in years if t <= year], default=None)
    if y is None:
        return None
    col = cols[y]
    for i in range(rd.shape[0]):
        label = rd.iat[i,0]
        if isinstance(label,str) and re.search(label_regex, label, re.IGNORECASE):
            try:
                return float(rd.iat[i, col])
            except Exception:
                return None
    return None

def extract_metrics_for_empresa(rd: pd.DataFrame, empresa_num: int, metrics_like: List[str]) -> pd.DataFrame:
    cols = get_empresa_columns(rd, empresa_num)
    years = sorted(cols.keys())
    rows, labels = [], []
    for i in range(rd.shape[0]):
        label = rd.iat[i,0]
        if isinstance(label,str) and any(re.search(rx, label, re.IGNORECASE) for rx in metrics_like):
            row_vals = [rd.iat[i, cols[y]] if y in cols else np.nan for y in years]
            if any(pd.notna(row_vals)):
                rows.append(row_vals); labels.append(label)
    return pd.DataFrame(rows, index=labels, columns=years)

# ------------------------
# Presence / Competition
# ------------------------
@dataclass
class Presence:
    country: str
    year: Optional[int]
    mode: Optional[str]

def parse_entry_text(s: str) -> Tuple[Optional[int], Optional[str]]:
    if not isinstance(s,str):
        return None, None
    m = re.search(r"((?:19|20)\d{2}).*?(FDI|JV)", s, re.IGNORECASE)
    if m:
        return int(m.group(1)), m.group(2).upper()
    m2 = re.search(r"((?:19|20)\d{2})", s)
    return (int(m2.group(1)), None) if m2 else (None, None)

def extract_presence_for_team(cp: pd.DataFrame, team_label_regex=r"T4\s*-\s*") -> List[Presence]:
    row2 = cp.iloc[2,:]
    col_t = None
    for j,v in row2.items():
        if isinstance(v,str) and re.search(team_label_regex, v, re.IGNORECASE):
            col_t = j; break
    if col_t is None:
        raise RuntimeError("Coluna do time não encontrada na aba 'Country Presence'.")
    out: List[Presence] = []
    for i in range(3, cp.shape[0]):
        country = cp.iat[i,0]
        if isinstance(country,str) and country.strip():
            entry = cp.iat[i, col_t]
            if isinstance(entry,str) and entry.strip():
                year, mode = parse_entry_text(entry)
                out.append(Presence(country=country.strip(), year=year, mode=mode))
    return out

def build_competition_accumulated(cp: pd.DataFrame) -> Dict[str, List[int]]:
    row2 = cp.iloc[2,:]
    team_cols = [j for j,v in row2.items() if isinstance(v,str) and re.search(r"\bT\d+\b", v)]
    by_country: Dict[str, List[int]] = {}
    for i in range(3, cp.shape[0]):
        country = cp.iat[i,0]
        if not (isinstance(country,str) and country.strip()):
            continue
        years = []
        for j in team_cols:
            entry = cp.iat[i,j]
            if isinstance(entry,str):
                cand = [int(y) for y in re.findall(r"(?:19|20)\d{2}", entry)]
                if cand:
                    years.append(min(cand))
        if years:
            by_country[country.strip()] = years
    return by_country

def competitors_at_year(by_country: Dict[str,List[int]], country: str, year: int) -> int:
    years = by_country.get(country, [])
    return sum(1 for y in years if y <= year)

# ------------------------
# Pricing / Margins
# ------------------------
def read_price_categories(xls) -> List[Tuple[str, float]]:
    try:
        cfg = pd.read_excel(xls, sheet_name="Config!", header=None)
        for i in range(0, 8):
            if str(cfg.iat[i,12]).lower().startswith("categories") and "price" in str(cfg.iat[i,13]).lower():
                cats = []
                for r in range(i+1, i+6):
                    name = str(cfg.iat[r,12]).strip()
                    mult = pd.to_numeric(cfg.iat[r,13], errors="coerce")
                    if name and pd.notna(mult):
                        cats.append((name, float(mult)))
                if cats:
                    return cats
    except Exception:
        pass
    return [("Muito Baixo",0.6),("Baixo",0.8),("Médio",1.0),("Alto",1.2),("Muito Alto",2.4)]

def margin_from_price_mult(mult: float) -> float:
    mapping = {0.6:0.10, 0.8:0.20, 1.0:0.25, 1.2:0.30, 2.4:0.40}
    if mult in mapping:
        return mapping[mult]
    lo, hi = 0.6, 2.4
    return 0.10 + (0.40-0.10)*max(0.0,min(1.0,(mult-lo)/(hi-lo)))

def _normalize_txt(x: str) -> str:
    if not isinstance(x,str):
        x = str(x)
    return _strip_accents(x).lower().strip()

def parse_price_overrides(s: Optional[str], price_cats: List[Tuple[str,float]]) -> Dict[str, float]:
    """
    s example: "United States:Médio,Canada:Baixo"
    Returns: dict {NormCountry: price_mult}
    """
    if not s:
        return {}
    name_to_mult = {}
    # map normalized category names to multiplier
    cat_map = { _normalize_txt(nm): mult for nm, mult in price_cats }
    cat_syn = {
        "medio":"médio","med":"médio",
        "very high":"muito alto","high":"alto","medium":"médio","low":"baixo","very low":"muito baixo"
    }
    for token in s.split(","):
        token = token.strip()
        if not token or ":" not in token:
            continue
        country, cat = token.split(":",1)
        catn = _normalize_txt(cat)
        catn = cat_syn.get(catn, catn)
        mult = cat_map.get(catn, None)
        if mult is None:
            for k in cat_map.keys():
                if catn in k or k in catn:
                    mult = cat_map[k]; break
        if mult is None:
            continue
        name_to_mult[ normalize_country(country) ] = float(mult)
    return name_to_mult

# ------------------------
# Elasticidade ε
# ------------------------
def calibrate_arpu_price(rd: pd.DataFrame, group: int) -> float:
    cols = get_empresa_columns(rd, group)
    years = sorted(cols.keys())
    def find_row(label_regex):
        for i in range(rd.shape[0]):
            lab = rd.iat[i,0]
            if isinstance(lab,str) and re.search(label_regex, lab, re.IGNORECASE):
                return i
        return None
    row_rev = find_row(r"^Your Revenues$")
    row_users = find_row(r"^Your Active Customers$")
    row_price = find_row(r"^Your price$")
    if row_rev is None or row_users is None or row_price is None:
        return 0.7
    xs, ys = [], []
    for y in years:
        try:
            rev = float(rd.iat[row_rev, cols[y]])
            users = float(rd.iat[row_users, cols[y]])
            price = float(rd.iat[row_price, cols[y]])
            if rev>0 and users>0 and price>0:
                arpu = rev / users
                xs.append(np.log(price)); ys.append(np.log(arpu))
        except Exception:
            pass
    if len(xs) >= 2:
        X = np.vstack([np.ones(len(xs)), xs]).T
        beta = np.linalg.lstsq(X, np.array(ys), rcond=None)[0]
        b = float(beta[1])
        epsilon = max(0.3, min(2.0, 1.0 - b))
        return float(epsilon)
    return 0.7

# ------------------------
# Region rates (MSE) & map
# ------------------------
def build_region_rates(xls) -> Dict[str, Dict[str, float]]:
    df = pd.read_excel(xls, sheet_name="MSE per country")
    df.columns = [str(c).strip() for c in df.columns]
    need = ["Region","Revenues","Cost of Products Sold","Total Marketing & Sales  Exp.","Fixed Costs\n(Adm. & Op.)","Opening Costs","Regulatory and political costs","Taxes"]
    for k in need:
        if k not in df.columns:
            raise RuntimeError("Coluna faltante em 'MSE per country': " + k)
    regions = {}
    for _,r in df.iterrows():
        region = str(r["Region"]).strip()
        if not region or region.lower()=="total":
            continue
        try:
            rev = float(r["Revenues"])
            mkt = float(r["Total Marketing & Sales  Exp."])
            cogs = float(r["Cost of Products Sold"])
            fixed = float(r["Fixed Costs\n(Adm. & Op.)"])
            opening = float(r["Opening Costs"])
            reg = float(r["Regulatory and political costs"])
            taxes = float(r["Taxes"])
        except Exception:
            continue
        pre_tax = max(0.0, rev - cogs - mkt - fixed - opening - reg)
        tax_rate = (taxes/pre_tax) if pre_tax>0 else 0.0
        regions[region] = {
            "fixed_rate": (fixed/rev) if rev>0 else 0.0,
            "opening_rate": (opening/rev) if rev>0 else 0.0,
            "reg_rate": (reg/rev) if rev>0 else 0.0,
            "tax_rate": max(0.0, min(0.5, tax_rate))
        }
    return regions

def build_country_region_map(xls) -> Dict[str,str]:
    try:
        df = pd.read_excel(xls, sheet_name="Population", header=0)
        df.columns = [str(c).strip() for c in df.columns]
        name_col = next((c for c in ["Name","Country Name","Country"] if c in df.columns), None)
        region_col = next((c for c in ["World","Region"] if c in df.columns), None)
        out = {}
        if name_col and region_col:
            for _,r in df.iterrows():
                nm = str(r[name_col]).strip()
                rg_pt = str(r[region_col]).strip()
                if nm and rg_pt and nm.lower() not in ["nan","none"]:
                    out[normalize_country(nm)] = normalize_region_pt_to_mse(rg_pt)
        return out
    except Exception:
        return {}

# ------------------------
# Price gap & affordability
# ------------------------
def price_gap_multiplier(price_mult: float, comp_price: float, gdp_aff: float, eta_gap: float, eta_disc: float) -> float:
    if comp_price is None or comp_price <= 0:
        comp_price = 1.0
    ratio = price_mult / comp_price
    if ratio >= 1.0:
        return math.exp(-eta_gap * (ratio - 1.0) / max(gdp_aff, 1e-3))
    else:
        return math.exp(+eta_disc * (1.0 - ratio) * gdp_aff)

def affordability_from_gdppc(gdppc: float, median_gdppc: float, alpha: float) -> float:
    if median_gdppc is None or median_gdppc <= 0:
        return 1.0
    r = max(0.1, min(5.0, gdppc/median_gdppc))
    return max(0.3, min(1.7, r**alpha))

# ------------------------
# Core model
# ------------------------
def p_cap(score: float, p_max: float, mode: str) -> float:
    s = max(0.0, min(1.0, score/100.0))
    if mode == "sqrt":
        return p_max * math.sqrt(s)
    return p_max * s

def estimate_profit(*, base_size: float, score: float, competitors: float, mkt_pc: float,
                    price_mult: float, margin_pct: float,
                    epsilon: float, p_max: float, k: float, gamma_comp: float, score_mode: str,
                    fixed_rate: float, reg_rate: float, opening_rate: float, tax_rate: float,
                    apply_opening: bool, comp_price: float, gdp_aff: float, eta_gap: float, eta_disc: float) -> Dict[str,float]:
    try:
        comp_val = float(competitors)
    except Exception:
        comp_val = 0.0
    comp_mult = 1.0 / (1.0 + float(gamma_comp) * max(comp_val, 0.0))
    base = (score/100.0)*p_max * (1.0 - math.exp(-k * mkt_pc)) * comp_mult
    P0 = min(p_cap(score, p_max, score_mode), base)
    pen = price_gap_multiplier(price_mult, comp_price, gdp_aff, eta_gap, eta_disc)
    P = P0 * pen
    rides_base = 6.0
    rides = rides_base * (1.0/max(price_mult,1e-6))**epsilon
    arpu = price_mult * rides
    revenue = base_size * P * arpu
    mb = revenue * margin_pct
    mkt_total = mkt_pc * base_size
    fixed = fixed_rate * revenue
    regpol = reg_rate * revenue
    opening = (opening_rate * revenue) if apply_opening else 0.0
    ebit = mb - mkt_total - fixed - regpol - opening
    taxes = max(0.0, tax_rate * ebit)
    net_income = ebit - taxes
    return {"P":P, "PricePenalty": (pen if P0>0 else 1.0), "ARPU":arpu, "Revenue":revenue, "EBIT":ebit, "NetIncome":net_income, "MKT_total":mkt_total}

def argmax_mkt_pc(*, base_size, score, competitors, price_mult, margin_pct, epsilon, p_max, k, gamma_comp, score_mode,
                  fixed_rate, reg_rate, opening_rate, tax_rate, apply_opening,
                  comp_price, gdp_aff, eta_gap, eta_disc,
                  objective="profit", alpha=0.7, rho=0.6,
                  lo=0.0, hi=0.03, tol=1e-5) -> Tuple[float, Dict[str,float]]:
    gr = (math.sqrt(5) - 1)/2
    a, b = lo, hi
    c = b - gr*(b-a)
    d = a + gr*(b-a)
    def f(x):
        est = estimate_profit(
            base_size=base_size, score=score, competitors=competitors, mkt_pc=x,
            price_mult=price_mult, margin_pct=margin_pct, epsilon=epsilon,
            p_max=p_max, k=k, gamma_comp=gamma_comp, score_mode=score_mode,
            fixed_rate=fixed_rate, reg_rate=reg_rate, opening_rate=opening_rate, tax_rate=tax_rate,
            apply_opening=apply_opening, comp_price=comp_price, gdp_aff=gdp_aff, eta_gap=eta_gap, eta_disc=eta_disc
        )
        if objective == "profit":
            return est["NetIncome"]
        growth_value = rho * base_size * est["P"] * est["ARPU"]
        return alpha*est["NetIncome"] + (1.0-alpha)*growth_value
    fc, fd = f(c), f(d)
    while abs(b-a) > tol:
        if fc < fd:
            a = c; c = d; fc = fd; d = a + gr*(b-a); fd = f(d)
        else:
            b = d; d = c; fd = fc; c = b - gr*(b-a); fc = f(c)
    x = (a+b)/2.0
    est = estimate_profit(
        base_size=base_size, score=score, competitors=competitors, mkt_pc=x,
        price_mult=price_mult, margin_pct=margin_pct, epsilon=epsilon,
        p_max=p_max, k=k, gamma_comp=gamma_comp, score_mode=score_mode,
        fixed_rate=fixed_rate, reg_rate=reg_rate, opening_rate=opening_rate, tax_rate=tax_rate,
        apply_opening=apply_opening, comp_price=comp_price, gdp_aff=gdp_aff, eta_gap=eta_gap, eta_disc=eta_disc
    )
    return x, est

# ------------------------
# Cash & index
# ------------------------
def read_cash_from_general_report(xls, group: int) -> Optional[float]:
    try:
        gr = pd.read_excel(xls, sheet_name="General Report", header=None)
    except Exception:
        return None
    header_row = None
    for i in range(min(140, gr.shape[0])):
        vals = [str(v) for v in gr.iloc[i,:].tolist()]
        if any("Empresa / jogador / equipe" in v for v in vals) and any("Disponibilidade de caixa" in v for v in vals):
            header_row = i; break
    if header_row is None:
        return None
    hdr = gr.iloc[header_row,:].astype(str).tolist()
    cash_col = next((j for j,h in enumerate(hdr) if "Disponibilidade de caixa" in h), None)
    if cash_col is None:
        return None
    patt = re.compile(fr"^T{group}\s*[-–]\s*", re.IGNORECASE)
    for i in range(header_row+1, min(header_row+80, gr.shape[0])):
        s0 = str(gr.iat[i,0] if i < gr.shape[0] else "")
        if patt.search(s0):
            try:
                return float(gr.iat[i, cash_col])
            except Exception:
                return None
    return None

def read_carryover_from_general_report(xls, group: int, year: int) -> Optional[float]:
    try:
        gr = pd.read_excel(xls, sheet_name="General Report", header=None)
    except Exception:
        return None
    header_row = None
    for i in range(min(160, gr.shape[0])):
        vals = [str(v) for v in gr.iloc[i,:].tolist()]
        if any("Empresa / jogador / equipe" in v for v in vals) and any(("Carry" in v) or ("Carry over" in v) for v in vals):
            header_row = i; break
    if header_row is None:
        return None
    hdr = gr.iloc[header_row,:].astype(str).tolist()
    carry_col = next((j for j,h in enumerate(hdr) if ("Carry" in h or "Carry over" in h)), None)
    if carry_col is None:
        return None
    patt = re.compile(fr"^T{group}\s*[-–]\s*", re.IGNORECASE)
    best = None
    for i in range(header_row+1, min(header_row+120, gr.shape[0])):
        s0 = str(gr.iat[i,0] if i < gr.shape[0] else "")
        if patt.search(s0):
            try:
                v = float(gr.iat[i, carry_col])
                best = v
            except Exception:
                continue
    return best

def minmax(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce").astype(float)
    if s.notna().sum()<=1 or np.isclose(s.max(), s.min(), equal_nan=True):
        return pd.Series(0.0, index=s.index)
    return (s - s.min())/(s.max()-s.min())

def attractiveness_index(macro_y1: pd.DataFrame) -> pd.Series:
    snap_agg = (macro_y1.groupby("Country", as_index=False)
                    .agg({"Population":"max", "GDPpc":"max"})).set_index("Country")
    pop_norm = minmax(snap_agg["Population"])
    gdp_norm = minmax(snap_agg["GDPpc"]) if "GDPpc" in snap_agg.columns else pd.Series(0.0, index=snap_agg.index)
    return 100*(0.6*pop_norm + 0.4*gdp_norm)

# ------------------------
# Main pipeline
# ------------------------
def decide_for_group(xlsx_path: str, group: int, decision_year: int, cash_cap_pct: float=0.50,
                     pop_sheet: Optional[str]=None, country_col: Optional[str]=None, year_header_row: Optional[int]=None,
                     gdp_year_header_row: Optional[int]=None, gdp_header_auto: bool=False, gdp_country_col: Optional[str]=None,
                     min_pop_m: float=10.0, min_score: float=15.0, min_year: int=2008,
                     p_max: float=0.03, k: float=120.0, gamma_comp: float=0.30, score_mode: str="sqrt",
                     eta_gap: float=0.75, eta_disc: float=0.25, aff_alpha: float=0.50, ma_quantile: float=0.60,
                     epsilon_override: Optional[float]=None,
                     base_source: str="population", demand_sheet: str="Market Analyzes",
                     k_owned: Optional[float]=None, pmax_owned_mult: float=1.0,
                     objective: str="profit", alpha_blend: float=0.7, rho_default: float=0.6,
                     price_override: Optional[str]=None, min_mkt_owned_pc: float=0.0, min_mkt_owned_total: float=0.0, lock_price_owned: bool=False,
                     target_share: Optional[str]=None, share_penalty: float=0.0,
                     debug: bool=False):

    xls = read_xls(xlsx_path)
    rd = read_sheet(xls, "Result data", header=None)
    cp = read_sheet(xls, "Country Presence", header=None)

    macro_long = build_macro_with_units(xls,
                             pop_sheet or "Population",
                             country_col or "Name",
                             1 if year_header_row is None else year_header_row,
                             gdp_year_header_row, gdp_header_auto, gdp_country_col,
                             min_year=min_year, debug=debug)

    # snapshot pro Y+1; se faltou, pega o mais próximo
    macro_y1 = macro_long[macro_long["Year"]==(decision_year+1)].copy()
    if macro_y1.empty:
        g = macro_long.copy()
        g["year_diff"] = (g["Year"] - (decision_year+1)).abs()
        idx = g.groupby("Country")["year_diff"].idxmin()
        macro_y1 = g.loc[idx].drop(columns=["year_diff"]).copy()
        macro_y1["Year"] = decision_year+1
    macro_y1 = macro_y1.sort_values("Population", ascending=False).drop_duplicates(subset=["Country"], keep="first").set_index("Country")

    # mapa canônico (normalizado -> como está no index do snapshot)
    idx_macro_norm = {normalize_country(n): n for n in macro_y1.index}

    gdppc_series = pd.to_numeric(macro_y1["GDPpc"], errors="coerce")
    gdppc_median = float(gdppc_series[gdppc_series>0].median(skipna=True)) if gdppc_series.notna().any() else 1.0

    comp_price = read_metric_value_for_year(rd, group, r"^Average Competitor price$", decision_year) or 1.0
    comp_by_country = build_competition_accumulated(cp)
    team_regex = fr"T{group}\s*-\s*"
    pres = extract_presence_for_team(cp, team_label_regex=team_regex)

    owned_names_pt = [p.country for p in pres if p.year and p.year <= decision_year]
    # Canonical owned list (dedup case-insensitive)
    owned = []
    seen = set()
    for nm in owned_names_pt:
        key = normalize_country(nm)
        canon = idx_macro_norm.get(key)
        if canon and canon.lower() not in seen:
            owned.append(canon); seen.add(canon.lower())

    # Demanda (se configurado)
    demand_map = None
    if base_source.lower().startswith("dem"):
        dem = extract_demand_table(xls, sheet=demand_sheet)
        if not dem.empty:
            demand_map = dict(zip(dem["NormCountry"], dem["Demand"]))

    def base_for_country(cname: str) -> float:
        if demand_map is not None:
            v = demand_map.get(normalize_country(cname), None)
            if v is not None and np.isfinite(v) and v>0:
                return float(v)
        return float(pd.to_numeric(macro_y1.at[cname, "Population"], errors="coerce"))

    idx_series = attractiveness_index(macro_y1.reset_index())

    last_cash = read_cash_from_general_report(xls, group)
    cash_cap = (cash_cap_pct * last_cash) if last_cash is not None else None

    epsilon_cal = calibrate_arpu_price(rd, group)
    epsilon = float(epsilon_override) if (epsilon_override is not None) else epsilon_cal

    region_rates = build_region_rates(xls)
    country_region = build_country_region_map(xls)

    price_cats = read_price_categories(xls)
    # Mapeamentos de categoria textual -> multiplicador
    cat_name_to_mult = { _strip_accents(nm).lower().strip(): mult for nm, mult in price_cats }

    # Overrides: normalizados -> mult
    override_map_norm = parse_price_overrides(price_override, price_cats) if price_override else {}
    # Overrides canônicos: usando o nome do macro_y1
    override_map_canon: Dict[str,float] = {}
    for norm_name, mult in override_map_norm.items():
        canon = idx_macro_norm.get(norm_name)
        if canon in macro_y1.index:
            override_map_canon[canon] = mult

    # Gate 2.4x
    allow_ma = set()
    if ma_quantile >= 0.0:
        threshold = float(pd.to_numeric(macro_y1["GDPpc"], errors="coerce").quantile(ma_quantile))
        for c in macro_y1.index:
            try:
                if float(pd.to_numeric(macro_y1.at[c, "GDPpc"], errors="coerce")) >= threshold:
                    allow_ma.add(c)
            except Exception:
                pass

    rho = read_carryover_from_general_report(xls, group, decision_year) or rho_default

    # Target share map
    ts_map: Dict[str, float] = {}
    if target_share:
        for token in str(target_share).split(","):
            token = token.strip()
            if not token or ":" not in token:
                continue
            nm, val = token.split(":",1)
            try:
                ts_map[normalize_country(nm)] = float(val)
            except Exception:
                continue

    def affordability(cname: str) -> float:
        gdppc = float(pd.to_numeric(macro_y1.at[cname,"GDPpc"], errors="coerce"))
        return affordability_from_gdppc(gdppc, gdppc_median, aff_alpha)

    def penalized_value(est: Dict[str,float], base_size: float, country_name: Optional[str]) -> float:
        if objective == "profit":
            val = est["NetIncome"]
        else:
            growth_value = rho * base_size * est["P"] * est["ARPU"]
            val = alpha_blend*est["NetIncome"] + (1.0-alpha_blend)*growth_value
        if share_penalty and share_penalty>0 and country_name:
            targ = ts_map.get(normalize_country(country_name))
            if targ is not None and targ > 0:
                shortfall = max(0.0, targ - est["P"])
                val -= float(share_penalty) * base_size * shortfall * est["ARPU"]
        return val

    # ---------------- Owned ----------------
    owned_rows = []
    for c in owned:
        base_size = base_for_country(c)
        score = float(idx_series.get(c, 0.0))
        gdp_aff = affordability(c)
        competitors = float(competitors_at_year(comp_by_country, c, decision_year+1))
        region = country_region.get(normalize_country(c), None)
        rr = region_rates.get(region, {"fixed_rate":0.02,"reg_rate":0.005,"opening_rate":0.0,"tax_rate":0.20})

        # price list (com override canônico)
        cat_list = read_price_categories(xls)
        applied_override = False
        if c in override_map_canon:
            forced_mult = override_map_canon[c]
            forced_name = None
            for nm, mult in price_cats:
                if abs(mult - forced_mult) < 1e-9:
                    forced_name = nm; break
            if forced_name is None:
                # nome amigável genérico
                forced_name = f"forced({forced_mult:.2f}x)"
            applied_override = True
            if lock_price_owned:
                cat_list = [(forced_name, forced_mult)]
            else:
                others = [(nm,m) for (nm,m) in price_cats if abs(m - forced_mult) >= 1e-9]
                cat_list = [(forced_name, forced_mult)] + others

        best = None; best_cat=None; best_margin=None; best_pen=None; best_mkt_pc=0.0
        use_k = k_owned if (k_owned is not None) else k
        use_pmax = p_max * (pmax_owned_mult if pmax_owned_mult else 1.0)

        for cat, price_mult in cat_list:
            if abs(price_mult-2.4)<1e-6 and (ma_quantile>=0.0) and (c not in allow_ma):
                continue
            margin_pct = margin_from_price_mult(price_mult)

            # otimizador 1D em mkt_pc com função objetivo penalizada (target_share)
            gr = (math.sqrt(5) - 1)/2
            a, b = 0.0, p_max
            c1 = b - gr*(b-a); d1 = a + gr*(b-a)
            def obj(x):
                est_tmp = estimate_profit(
                    base_size=base_size, score=score, competitors=competitors, mkt_pc=x,
                    price_mult=price_mult, margin_pct=margin_pct, epsilon=epsilon,
                    p_max=use_pmax, k=use_k, gamma_comp=gamma_comp, score_mode=score_mode,
                    fixed_rate=rr.get('fixed_rate',0.02), reg_rate=rr.get('reg_rate',0.005), opening_rate=0.0, tax_rate=rr.get('tax_rate',0.20),
                    apply_opening=False, comp_price=comp_price, gdp_aff=gdp_aff, eta_gap=eta_gap, eta_disc=eta_disc
                )
                return penalized_value(est_tmp, base_size, c)
            f_c1, f_d1 = obj(c1), obj(d1)
            while abs(b-a) > 1e-5:
                if f_c1 < f_d1:
                    a = c1; c1 = d1; f_c1 = f_d1; d1 = a + gr*(b-a); f_d1 = obj(d1)
                else:
                    b = d1; d1 = c1; f_d1 = f_c1; c1 = b - gr*(b-a); f_c1 = obj(c1)
            mkt_pc_opt = (a+b)/2.0

            if min_mkt_owned_pc and mkt_pc_opt < min_mkt_owned_pc:
                mkt_pc_opt = min_mkt_owned_pc

            est = estimate_profit(
                base_size=base_size, score=score, competitors=competitors, mkt_pc=mkt_pc_opt,
                price_mult=price_mult, margin_pct=margin_pct, epsilon=epsilon,
                p_max=use_pmax, k=use_k, gamma_comp=gamma_comp, score_mode=score_mode,
                fixed_rate=rr.get('fixed_rate',0.02), reg_rate=rr.get('reg_rate',0.005), opening_rate=0.0, tax_rate=rr.get('tax_rate',0.20),
                apply_opening=False, comp_price=comp_price, gdp_aff=gdp_aff, eta_gap=eta_gap, eta_disc=eta_disc
            )

            if (best is None) or (est["NetIncome"] > best["NetIncome"]):
                best = est.copy(); best_cat=(cat, price_mult); best_margin=margin_pct; best_pen=est["PricePenalty"]; best_mkt_pc=mkt_pc_opt

        owned_rows.append({
            "Country": c,
            "Competitors(Y+1)": int(competitors),
            "Score(0-100)": round(float(idx_series.get(c, 0.0)),1),
            "GDPpc": float(pd.to_numeric(macro_y1.at[c,"GDPpc"], errors="coerce")),
            "PriceCat": best_cat[0] if best_cat else None,
            "Price_mult": best_cat[1] if best_cat else None,
            "Margin%": best_margin if best_margin is not None else None,
            "PricePenalty": best_pen if best_pen is not None else None,
            "AppliedOverride": bool(applied_override),
            "MKT_pc": best_mkt_pc if best else 0.0,
            "MKT_total": (best_mkt_pc*base_size) if best else 0.0,
            "Est_P": best["P"] if best else 0.0,
            "Est_ARPU": best["ARPU"] if best else 0.0,
            "Est_Revenue": best["Revenue"] if best else 0.0,
            "Est_NetIncome": best["NetIncome"] if best else 0.0
        })

    df_owned = pd.DataFrame(owned_rows)
    if not df_owned.empty:
        df_owned = df_owned.sort_values(["Country","Est_NetIncome"], ascending=[True,False]).drop_duplicates(subset=["Country"], keep="first")
        df_owned = df_owned.sort_values("Est_NetIncome", ascending=False)

    # enforce total mínimo
    if not df_owned.empty and min_mkt_owned_total and min_mkt_owned_total > 0:
        current = float(df_owned["MKT_total"].sum())
        if current < min_mkt_owned_total:
            scale = (min_mkt_owned_total / max(current, 1e-9))
            df_owned["MKT_total"] *= scale
            # recomputa MKT_pc coerente
            def _base(c): return base_for_country(c)
            df_owned["MKT_pc"] = df_owned.apply(lambda r: r["MKT_total"]/max(1.0,_base(r["Country"])), axis=1)

    remaining_cash = None
    if cash_cap_pct is not None and cash_cap_pct>=0 and read_cash_from_general_report is not None:
        last_cash = read_cash_from_general_report(xls, group)
        if last_cash is not None:
            cash_cap = cash_cap_pct * last_cash
        else:
            cash_cap = None
    else:
        cash_cap = None

    if cash_cap is not None and not df_owned.empty:
        spent_owned = float(df_owned["MKT_total"].sum())
        remaining_cash = cash_cap - spent_owned
    else:
        remaining_cash = cash_cap

    # ---------------- Novos países ----------------
    owned_set = set(owned)
    min_pop = 1_000_000 * float(min_pop_m)
    candidates = [c for c in macro_y1.index if c not in owned_set]
    candidates = [c for c in candidates if float(pd.to_numeric(macro_y1.at[c,"Population"], errors="coerce")) >= min_pop and float(idx_series.get(c,0.0)) >= float(min_score)]

    new_rows = []
    for c in candidates:
        base_size = base_for_country(c)
        score = float(idx_series.get(c, 0.0))
        gdp_aff = affordability(c)
        competitors = float(competitors_at_year(comp_by_country, c, decision_year+1))
        region = country_region.get(normalize_country(c), None)
        rr = region_rates.get(region, {"fixed_rate":0.02,"reg_rate":0.005,"opening_rate":0.03,"tax_rate":0.20})
        hi_pc_cap = p_max if remaining_cash is None else min(p_max, max(0.0, remaining_cash / max(base_size,1.0)))
        best=None; best_cat=None; best_margin=None; best_mode=None; best_pen=None; best_mkt_pc=0.0
        for cat, price_mult in read_price_categories(xls):
            if abs(price_mult-2.4)<1e-6 and (ma_quantile>=0.0) and (c not in allow_ma):
                continue
            margin_pct = margin_from_price_mult(price_mult)
            # FDI
            mkt_pc_fdi, est_fdi = argmax_mkt_pc(
                base_size=base_size, score=score, competitors=competitors, price_mult=price_mult, margin_pct=margin_pct,
                epsilon=epsilon, p_max=p_max, k=k, gamma_comp=gamma_comp, score_mode=score_mode,
                fixed_rate=rr.get('fixed_rate',0.02), reg_rate=rr.get('reg_rate',0.005), opening_rate=rr.get('opening_rate',0.03), tax_rate=rr.get('tax_rate',0.20),
                apply_opening=True, comp_price=comp_price, gdp_aff=gdp_aff, eta_gap=eta_gap, eta_disc=eta_disc,
                objective=objective, alpha=alpha_blend, rho=rho, lo=0.0, hi=hi_pc_cap, tol=1e-5
            )
            cand_est = est_fdi.copy(); cand_est["MKT_pc"]=mkt_pc_fdi; cand_est["Mode"]="FDI"; cand_est["PricePenalty"]=est_fdi["PricePenalty"]
            # JV
            mkt_pc_jv, est_jv = argmax_mkt_pc(
                base_size=base_size, score=score, competitors=competitors, price_mult=price_mult, margin_pct=margin_pct,
                epsilon=epsilon, p_max=p_max, k=k, gamma_comp=gamma_comp, score_mode=score_mode,
                fixed_rate=rr.get('fixed_rate',0.02), reg_rate=rr.get('reg_rate',0.005), opening_rate=rr.get('opening_rate',0.03)/2.0, tax_rate=rr.get('tax_rate',0.20),
                apply_opening=True, comp_price=comp_price, gdp_aff=gdp_aff, eta_gap=eta_gap, eta_disc=eta_disc,
                objective=objective, alpha=alpha_blend, rho=rho, lo=0.0, hi=hi_pc_cap, tol=1e-5
            )
            est_jv_parent = est_jv.copy(); est_jv_parent["NetIncome"] *= 0.5; est_jv_parent["MKT_pc"]=mkt_pc_jv; est_jv_parent["Mode"]="JV"; est_jv_parent["PricePenalty"]=est_jv["PricePenalty"]
            choice = cand_est if cand_est["NetIncome"] >= est_jv_parent["NetIncome"] else est_jv_parent
            if (best is None) or (choice["NetIncome"] > best["NetIncome"]):
                best = choice.copy(); best_cat=(cat, price_mult); best_margin=margin_pct; best_mode=choice["Mode"]; best_pen=choice["PricePenalty"]; best_mkt_pc=choice["MKT_pc"]
        if best is None: 
            continue
        new_rows.append({
            "Country": c,
            "Competitors(Y+1)": int(competitors),
            "Score(0-100)": round(score,1),
            "GDPpc": float(pd.to_numeric(macro_y1.at[c,"GDPpc"], errors="coerce")),
            "Mode": best_mode,
            "PriceCat": best_cat[0],
            "Price_mult": best_cat[1],
            "Margin%": best_margin,
            "PricePenalty": best_pen,
            "MKT_pc": best_mkt_pc,
            "MKT_total": best_mkt_pc*base_size,
            "Est_P": best["P"],
            "Est_ARPU": best["ARPU"],
            "Est_Revenue": best["Revenue"],
            "Est_NetIncome": best["NetIncome"]
        })
    df_new = pd.DataFrame(new_rows).sort_values("Est_NetIncome", ascending=False).head(3) if new_rows else pd.DataFrame()

    metrics_like = [r"Initial Cash", r"Operational Income", r"Profit \(Net income\)", r"Cash flow|Cash availability",
                    r"Marketing", r"Your Revenues", r"Your Active Customers", r"Your price", r"Average Competitor price",
                    r"Your Market Share"]
    metrics = extract_metrics_for_empresa(rd, group, metrics_like)

    return metrics, df_owned, df_new, cash_cap, owned, remaining_cash, comp_price, gdppc_median, epsilon, rho, base_source

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--group", type=int, required=True)
    ap.add_argument("--decision_year", type=int, required=True)
    ap.add_argument("--cash_cap_pct", type=float, default=0.50)
    ap.add_argument("--pop_sheet", type=str, default="Population")
    ap.add_argument("--country_col", type=str, default="Name")
    ap.add_argument("--year_header_row", type=int, default=1)
    ap.add_argument("--gdp_year_header_row", type=int, default=None)
    ap.add_argument("--gdp_header_auto", action="store_true")
    ap.add_argument("--gdp_country_col", type=str, default=None)
    ap.add_argument("--min_year", type=int, default=2008)
    ap.add_argument("--min_pop_m", type=float, default=10.0)
    ap.add_argument("--min_score", type=float, default=15.0)
    ap.add_argument("--p_max", type=float, default=0.03)
    ap.add_argument("--k", type=float, default=120.0)
    ap.add_argument("--gamma_comp", type=float, default=0.30)
    ap.add_argument("--score_mode", choices=["linear","sqrt"], default="sqrt")
    ap.add_argument("--eta_gap", type=float, default=0.75)
    ap.add_argument("--eta_disc", type=float, default=0.25)
    ap.add_argument("--aff_alpha", type=float, default=0.50)
    ap.add_argument("--ma_quantile", type=float, default=0.60)
    ap.add_argument("--epsilon_override", type=float, default=None)
    ap.add_argument("--base_source", choices=["population","demand"], default="population")
    ap.add_argument("--demand_sheet", type=str, default="Market Analyzes")
    ap.add_argument("--k_owned", type=float, default=None)
    ap.add_argument("--pmax_owned_mult", type=float, default=1.0)
    ap.add_argument("--objective", choices=["profit","blended"], default="profit")
    ap.add_argument("--alpha_blend", type=float, default=0.7)
    ap.add_argument("--rho_default", type=float, default=0.6)
    ap.add_argument("--price_override", type=str, default=None)
    ap.add_argument("--min_mkt_owned_pc", type=float, default=0.0)
    ap.add_argument("--min_mkt_owned_total", type=float, default=0.0)
    ap.add_argument("--lock_price_owned", action="store_true")
    ap.add_argument("--target_share", type=str, default=None, help="Ex: 'United States:0.05,Canada:0.02' (fração 0-1 por país)")
    ap.add_argument("--share_penalty", type=float, default=0.0, help="Peso da penalidade (em unidades ~Receita)")
    ap.add_argument("--list_sheets", action="store_true")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    if args.list_sheets:
        xls = pd.ExcelFile(args.xlsx)
        print("Abas encontradas:")
        for s in xls.sheet_names:
            print(" -", s)
        return

    metrics, df_owned, df_new, cash_cap, owned, remaining_cash, comp_price, gdppc_median, eps, rho, base_source = decide_for_group(
        xlsx_path=args.xlsx, group=args.group, decision_year=args.decision_year, cash_cap_pct=args.cash_cap_pct,
        pop_sheet=args.pop_sheet, country_col=args.country_col, year_header_row=args.year_header_row,
        gdp_year_header_row=args.gdp_year_header_row, gdp_header_auto=args.gdp_header_auto, gdp_country_col=args.gdp_country_col,
        min_pop_m=args.min_pop_m, min_score=args.min_score, min_year=args.min_year,
        p_max=args.p_max, k=args.k, gamma_comp=args.gamma_comp, score_mode=args.score_mode,
        eta_gap=args.eta_gap, eta_disc=args.eta_disc, aff_alpha=args.aff_alpha, ma_quantile=args.ma_quantile,
        epsilon_override=args.epsilon_override, base_source=args.base_source, demand_sheet=args.demand_sheet,
        k_owned=args.k_owned, pmax_owned_mult=args.pmax_owned_mult, objective=args.objective,
        alpha_blend=args.alpha_blend, rho_default=args.rho_default,
        price_override=args.price_override, min_mkt_owned_pc=args.min_mkt_owned_pc, min_mkt_owned_total=args.min_mkt_owned_total,
        lock_price_owned=args.lock_price_owned, target_share=args.target_share, share_penalty=args.share_penalty,
        debug=args.debug
    )

    print(f"\n=== Grupo: {args.group} | Ano de decisão: {args.decision_year} (resultado em {args.decision_year+1} ) ===")
    if cash_cap is not None:
        print(f"Cap de MKT ( {int(args.cash_cap_pct*100)} % do caixa do ano): ~US$ {round(float(cash_cap),2)}")
    print(f"ε (elasticidade): {eps:.3f} | Avg Competitor price: {comp_price:.3f} | GDPpc mediana: {gdppc_median:,.2f} | rho(carry): {rho:.2f} | base={base_source}")

    print("\nPaíses já presentes do grupo:", ", ".join([str(o) for o in owned]) if owned else "(nenhum)")

    print("\n--- JÁ PRESENTES (ótimo por preço, margem, MKT_pc) ---")
    if not df_owned.empty:
        cols = ["Country","Score(0-100)","GDPpc","Competitors(Y+1)","PriceCat","Price_mult","Margin%","PricePenalty","AppliedOverride","MKT_pc","MKT_total","Est_P","Est_ARPU","Est_Revenue","Est_NetIncome"]
        print(df_owned[cols].to_string(index=False, justify='left', float_format=lambda v: f"{v:,.4f}"))
    else:
        print("(sem países ativos até o ano da decisão)")

    if remaining_cash is not None:
        print(f"\nCaixa remanescente para ENTRADA (após MKT em ativos): ~US$ {round(float(remaining_cash),2)}")

    print("\n--- ENTRADA (Top 3: modo JV/FDI, preço, margem cat., MKT_pc sob cap) ---")
    if not df_new.empty:
        cols = ["Country","Score(0-100)","GDPpc","Competitors(Y+1)","Mode","PriceCat","Price_mult","Margin%","PricePenalty","MKT_pc","MKT_total","Est_P","Est_ARPU","Est_Revenue","Est_NetIncome"]
        print(df_new[cols].to_string(index=False, justify='left', float_format=lambda v: f"{v:,.4f}"))
    else:
        print("(sem candidatos)")

if __name__ == "__main__":
    main()

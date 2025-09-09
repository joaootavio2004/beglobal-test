#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Be Global — Decision Helper (v0.2.7)
------------------------------------
• Lê o XLSX “Decisões e Relatório” e recomenda alocações por país maximizando Lucro.
• Considera: preço (categoria→margem), elasticidade ε, concorrência, JV vs FDI, MSE (fixos/abertura/reg), cap de caixa,
  penetração vs MKT_pc (teto por score) e penalização por gap de preço modulado por acessibilidade (GDPpc).
• Blindagens: parser numérico robusto (notação científica e formato europeu), merge por país normalizado,
  cabeçalho independente da aba GDP, filtro de anos <= min_year (default 2008), chamadas com argumentos nomeados.
"""
import argparse, re, math, warnings, unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", message="Unknown extension is not supported and will be removed")
warnings.filterwarnings("ignore", message="Conditional Formatting extension is not supported and will be removed")

# ------------------------
# Utils & normalization
# ------------------------
def read_xls(xlsx_path: str):
    return pd.ExcelFile(xlsx_path)

def read_sheet(xls, name: str, header=None) -> pd.DataFrame:
    return pd.read_excel(xls, sheet_name=name, header=header)

def _strip_accents(s: str) -> str:
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
# GDP/Population parsing
# ------------------------
def detect_year_header_row(xls, sheet: str, max_rows: int = 6) -> int:
    df = pd.read_excel(xls, sheet_name=sheet, header=None)
    yr_re = re.compile(r"(?:19|20)\d{2}")
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
    # direct parse (handles 1.23e+12)
    v = pd.to_numeric(s, errors="coerce")
    if pd.notna(v):
        return v
    s2 = s.replace(" ", "")
    # 1.234.567,89 -> 1234567.89
    if "," in s2 and s2.count(",")==1 and s2.rsplit(",",1)[1].isdigit():
        s3 = s2.replace(".", "").replace(",", ".")
        v = pd.to_numeric(s3, errors="coerce")
        if pd.notna(v):
            return v
    # strip non-numeric except exponent markers
    s4 = re.sub(r"[^0-9eE+\-\.]", "", s2)
    return pd.to_numeric(s4, errors="coerce")

def extract_year_long_table(xls, sheet: str, country_col: Optional[str], year_header_row: Optional[int], value_label: str, min_year: int = 2008) -> pd.DataFrame:
    df = pd.read_excel(xls, sheet_name=sheet, header=None if year_header_row is not None else 0)
    if year_header_row is not None:
        header = df.iloc[year_header_row,:].tolist()
        # choose country column
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
        # map year columns
        year_map = {}
        for j, v in enumerate(header):
            m = re.search(r"(?:19|20)\d{2}", str(v))
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
        # country col
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
        # year columns
        year_cols = []
        for c in df.columns:
            m = re.search(r"(?:19|20)\d{2}", str(c))
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

def build_macro(xls, pop_sheet: str, country_col: str, year_header_row: int,
                gdp_year_header_row: Optional[int] = None, gdp_auto: bool = False, gdp_country_col: Optional[str] = None,
                min_year: int = 2008, debug: bool=False) -> pd.DataFrame:
    pop = extract_year_long_table(xls, pop_sheet, country_col, year_header_row, "Population", min_year=min_year)
    gdp_hdr = detect_year_header_row(xls, "GDP") if gdp_auto else (gdp_year_header_row if gdp_year_header_row is not None else year_header_row)
    gdp_col = gdp_country_col if gdp_country_col is not None else country_col
    gdp = extract_year_long_table(xls, "GDP", gdp_col, gdp_hdr, "GDP", min_year=min_year)
    # normalize and merge
    pop = pop.copy(); gdp = gdp.copy()
    pop["NormCountry"] = pop["Country"].map(normalize_country)
    gdp["NormCountry"] = gdp["Country"].map(normalize_country)
    df = pd.merge(pop.rename(columns={"Country":"PopCountry"}),
                  gdp.rename(columns={"Country":"GdpCountry"}),
                  on=["NormCountry","Year"], how="left")
    # Use o nome original da aba Population para exibição
    df = df.rename(columns={"PopCountry":"Country"})
    # fallback: try alternate sheet if GDP missing a lot
    if ("GDP" not in df.columns) or (df["GDP"].isna().mean() > 0.50):
        try:
            alt_hdr = detect_year_header_row(xls, "GDP and Pop. Country Comparison") if gdp_auto else (gdp_year_header_row if gdp_year_header_row is not None else year_header_row)
            alt_col = gdp_country_col if gdp_country_col is not None else country_col
            gdp_alt = extract_year_long_table(xls, "GDP and Pop. Country Comparison", alt_col, alt_hdr, "GDP", min_year=min_year)
            if not gdp_alt.empty:
                gdp_alt["NormCountry"] = gdp_alt["Country"].map(normalize_country)
                df = pd.merge(pop.drop(columns=["Country"]), gdp_alt.drop(columns=["Country"]), on=["NormCountry","Year"], how="left")
                df = df.rename(columns={"NormCountry":"Country"})
                if debug:
                    cov = 1.0 - df["GDP"].isna().mean()
                    print(f"[debug] GDP fallback aplicado ('GDP and Pop. Country Comparison'): cobertura={cov:.1%}")
        except Exception as e:
            if debug:
                print("[debug] Falha no fallback GDP alt:", e)
    df["GDPpc"] = df["GDP"] / df["Population"]
    # --- unit auto-scaling ---
    def _safe_percentile(s, q):
        s2 = pd.to_numeric(s, errors="coerce")
        s2 = s2[np.isfinite(s2)]
        return float(np.percentile(s2, q)) if len(s2)>0 else np.nan
    # Pop: fix negatives and scale heuristics
    df["Population"] = pd.to_numeric(df["Population"], errors="coerce")
    df.loc[df["Population"]<0, "Population"] = df.loc[df["Population"]<0, "Population"].abs()
    p95_pop = _safe_percentile(df["Population"], 95)
    pop_scale = 1.0
    if np.isfinite(p95_pop):
        if p95_pop < 2:        pop_scale = 1e9   # bilhões
        elif p95_pop < 2000:   pop_scale = 1e6   # milhões
        elif p95_pop < 2e6:    pop_scale = 1e3   # milhares (raro)
    df["Population"] = df["Population"] * pop_scale
    # GDP initial scale
    df["GDP"] = pd.to_numeric(df["GDP"], errors="coerce")
    # gdppc raw median (positivos)
    gdppc_raw = df["GDP"] / df["Population"]
    med_raw = float(gdppc_raw[gdppc_raw>0].median(skipna=True)) if gdppc_raw.notna().any() else np.nan
    gdp_scale = 1.0
    if np.isfinite(med_raw) and med_raw>0:
        target = 10000.0
        guess = target / med_raw
        # escolha discreta mais próxima
        choices = [1.0, 1e3, 1e6, 1e9, 1e12]
        gdp_scale = min(choices, key=lambda z: abs(z - guess))
    df["GDP"] = df["GDP"] * gdp_scale
    df["GDPpc"] = df["GDP"] / df["Population"]
    if debug:
        print(f"[debug] unit scales → pop_scale={pop_scale:g}, gdp_scale={gdp_scale:g}")
    if debug:
        # samples for target-ish years (first available row per probe)
        for probe in ["United States","Canada","China","India","Germany"]:
            sub = df[df["Country"].str.lower()==probe.lower()].sort_values("Year")
            if not sub.empty:
                y = int(sub["Year"].iloc[-1])
                g = sub["GDP"].iloc[-1]
                p = sub["Population"].iloc[-1]
                pc = sub["GDPpc"].iloc[-1]
                print(f"[debug] sample {probe} last-year~{y}: GDP={g:.3g}, Pop={p:.3g}, GDPpc={pc:.3g}")
    return df

def snapshot_macro(macro_long: pd.DataFrame, target_year: int) -> pd.DataFrame:
    if target_year in macro_long["Year"].unique():
        snap = macro_long[macro_long["Year"]==target_year].copy()
    else:
        g = macro_long.copy()
        g["year_diff"] = (g["Year"] - target_year).abs()
        idx = g.groupby("Country")["year_diff"].idxmin()
        snap = g.loc[idx].drop(columns=["year_diff"]).copy()
        snap["Year"] = target_year
    return snap

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
# Country Presence
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
# Price config & margins
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

def estimate_profit(*, pop: float, score: float, competitors: float, mkt_pc: float,
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
    revenue = pop * P * arpu
    mb = revenue * margin_pct
    mkt_total = mkt_pc * pop
    fixed = fixed_rate * revenue
    regpol = reg_rate * revenue
    opening = (opening_rate * revenue) if apply_opening else 0.0
    ebit = mb - mkt_total - fixed - regpol - opening
    taxes = max(0.0, tax_rate * ebit)
    net_income = ebit - taxes
    return {"P":P, "PricePenalty": (pen if P0>0 else 1.0), "ARPU":arpu, "Revenue":revenue, "EBIT":ebit, "NetIncome":net_income, "MKT_total":mkt_total}

def argmax_mkt_pc(pop, score, competitors, price_mult, margin_pct, epsilon, p_max, k, gamma_comp, score_mode,
                  fixed_rate, reg_rate, opening_rate, tax_rate, apply_opening,
                  comp_price, gdp_aff, eta_gap, eta_disc, lo=0.0, hi=0.03, tol=1e-5) -> Tuple[float, Dict[str,float]]:
    gr = (math.sqrt(5) - 1)/2
    a, b = lo, hi
    c = b - gr*(b-a)
    d = a + gr*(b-a)
    def f(x):
        return estimate_profit(
            pop=pop, score=score, competitors=competitors, mkt_pc=x,
            price_mult=price_mult, margin_pct=margin_pct, epsilon=epsilon,
            p_max=p_max, k=k, gamma_comp=gamma_comp, score_mode=score_mode,
            fixed_rate=fixed_rate, reg_rate=reg_rate, opening_rate=opening_rate, tax_rate=tax_rate,
            apply_opening=apply_opening, comp_price=comp_price, gdp_aff=gdp_aff,
            eta_gap=eta_gap, eta_disc=eta_disc
        )["NetIncome"]
    fc, fd = f(c), f(d)
    while abs(b-a) > tol:
        if fc < fd:
            a = c; c = d; fc = fd; d = a + gr*(b-a); fd = f(d)
        else:
            b = d; d = c; fd = fc; c = b - gr*(b-a); fc = f(c)
    x = (a+b)/2.0
    est = estimate_profit(
        pop=pop, score=score, competitors=competitors, mkt_pc=x,
        price_mult=price_mult, margin_pct=margin_pct, epsilon=epsilon,
        p_max=p_max, k=k, gamma_comp=gamma_comp, score_mode=score_mode,
        fixed_rate=fixed_rate, reg_rate=reg_rate, opening_rate=opening_rate, tax_rate=tax_rate,
        apply_opening=apply_opening, comp_price=comp_price, gdp_aff=gdp_aff,
        eta_gap=eta_gap, eta_disc=eta_disc
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
                     epsilon_override: Optional[float]=None, debug: bool=False):
    xls = read_xls(xlsx_path)
    rd = read_sheet(xls, "Result data", header=None)
    cp = read_sheet(xls, "Country Presence", header=None)

    macro_long = build_macro(xls,
                             pop_sheet or "Population",
                             country_col or "Name",
                             1 if year_header_row is None else year_header_row,
                             gdp_year_header_row, gdp_header_auto, gdp_country_col,
                             min_year=min_year, debug=debug)

    macro_y1 = snapshot_macro(macro_long, decision_year+1)
    macro_y1 = macro_y1.sort_values("Population", ascending=False).drop_duplicates(subset=["Country"], keep="first").set_index("Country")

    gdppc_series = pd.to_numeric(macro_y1["GDPpc"], errors="coerce")
    gdppc_median = float(gdppc_series[gdppc_series>0].median(skipna=True))
    if not np.isfinite(gdppc_median) or gdppc_median <= 0:
        tmp = gdppc_series.median(skipna=True)
        gdppc_median = float(tmp) if pd.notna(tmp) else 1.0
        if not np.isfinite(gdppc_median) or gdppc_median <= 0:
            gdppc_median = 1.0
            if debug:
                print("[hint] GDPpc mediana <= 0: usando fallback=1.0 (verifique cabeçalhos/coluna de país da aba GDP)")

    comp_price = read_metric_value_for_year(rd, group, r"^Average Competitor price$", decision_year) or 1.0
    comp_by_country = build_competition_accumulated(cp)
    team_regex = fr"T{group}\s*-\s*"
    pres = extract_presence_for_team(cp, team_label_regex=team_regex)
    idx_macro_norm = {normalize_country(n): n for n in macro_y1.index}
    owned_names_pt = [p.country for p in pres if p.year and p.year <= decision_year]
    owned = [idx_macro_norm.get(normalize_country(nm)) for nm in owned_names_pt if normalize_country(nm) in idx_macro_norm]
    owned = [x for x in owned if x]

    idx_series = attractiveness_index(macro_y1.reset_index())
    last_cash = read_cash_from_general_report(xls, group)
    cash_cap = (cash_cap_pct * last_cash) if last_cash is not None else None

    epsilon_cal = calibrate_arpu_price(rd, group)
    epsilon = float(epsilon_override) if (epsilon_override is not None) else epsilon_cal
    region_rates = build_region_rates(xls)
    country_region = build_country_region_map(xls)
    price_cats = read_price_categories(xls)

    allow_ma = set()
    if ma_quantile >= 0.0:
        threshold = float(pd.to_numeric(macro_y1["GDPpc"], errors="coerce").quantile(ma_quantile))
        for c in macro_y1.index:
            try:
                if float(pd.to_numeric(macro_y1.at[c, "GDPpc"], errors="coerce")) >= threshold:
                    allow_ma.add(c)
            except Exception:
                pass

    # Owned
    owned_rows = []
    for c in owned:
        if c not in macro_y1.index: continue
        pop = float(pd.to_numeric(macro_y1.at[c,"Population"], errors="coerce"))
        score = float(idx_series.get(c, 0.0))
        gdppc = float(pd.to_numeric(macro_y1.at[c,"GDPpc"], errors="coerce"))
        gdp_aff = affordability_from_gdppc(gdppc, gdppc_median, aff_alpha)
        competitors = float(competitors_at_year(comp_by_country, c, decision_year+1))
        region = country_region.get(normalize_country(c), None)
        rr = region_rates.get(region, {"fixed_rate":0.02,"reg_rate":0.005,"opening_rate":0.0,"tax_rate":0.20})
        best = None; best_cat=None; best_margin=None; best_pen=None
        for cat, price_mult in price_cats:
            if abs(price_mult-2.4)<1e-6 and (ma_quantile>=0.0) and (c not in allow_ma):
                continue
            margin_pct = margin_from_price_mult(price_mult)
            mkt_pc_opt, est = argmax_mkt_pc(pop, score, competitors, price_mult, margin_pct, epsilon, p_max, k, gamma_comp, score_mode,
                                            rr.get('fixed_rate',0.02), rr.get('reg_rate',0.005), 0.0, rr.get('tax_rate',0.20),
                                            False, comp_price, gdp_aff, eta_gap, eta_disc, lo=0.0, hi=p_max, tol=1e-5)
            if (best is None) or (est["NetIncome"] > best["NetIncome"]):
                best = est.copy(); best["MKT_pc"] = mkt_pc_opt; best_cat = (cat, price_mult); best_margin = margin_pct; best_pen = est["PricePenalty"]
        owned_rows.append({
            "Country": c,
            "Competitors(Y+1)": int(competitors),
            "Score(0-100)": round(score,1),
            "GDPpc": gdppc,
            "PriceCat": best_cat[0] if best_cat else None,
            "Price_mult": best_cat[1] if best_cat else None,
            "Margin%": best_margin if best_margin is not None else None,
            "PricePenalty": best_pen if best_pen is not None else None,
            "MKT_pc": best["MKT_pc"] if best else 0.0,
            "MKT_total": (best["MKT_pc"]*pop) if best else 0.0,
            "Est_P": best["P"] if best else 0.0,
            "Est_ARPU": best["ARPU"] if best else 0.0,
            "Est_Revenue": best["Revenue"] if best else 0.0,
            "Est_NetIncome": best["NetIncome"] if best else 0.0
        })
    df_owned = pd.DataFrame(owned_rows).sort_values("Est_NetIncome", ascending=False) if owned_rows else pd.DataFrame()

    # Cap de caixa em owned
    if cash_cap is not None and not df_owned.empty:
        total_owned = float(df_owned["MKT_total"].sum())
        if total_owned > cash_cap and total_owned > 0:
            scale = cash_cap / total_owned
            df_owned["MKT_total"] *= scale
            df_owned["MKT_pc"] = df_owned.apply(lambda r: r["MKT_total"] / float(macro_y1.at[r["Country"],"Population"]), axis=1)
    spent_owned = float(df_owned["MKT_total"].sum()) if not df_owned.empty else 0.0
    remaining_cash = (cash_cap - spent_owned) if cash_cap is not None else None

    # Candidatos (novos)
    owned_set = set(owned)
    min_pop = 1_000_000 * float(min_pop_m)
    candidates = [c for c in macro_y1.index if c not in owned_set]
    candidates = [c for c in candidates if float(pd.to_numeric(macro_y1.at[c,"Population"], errors="coerce")) >= min_pop and float(idx_series.get(c,0.0)) >= float(min_score)]

    new_rows = []
    for c in candidates:
        pop = float(pd.to_numeric(macro_y1.at[c,"Population"], errors="coerce"))
        score = float(idx_series.get(c, 0.0))
        gdppc = float(pd.to_numeric(macro_y1.at[c,"GDPpc"], errors="coerce"))
        gdp_aff = affordability_from_gdppc(gdppc, gdppc_median, aff_alpha)
        competitors = float(competitors_at_year(comp_by_country, c, decision_year+1))
        region = country_region.get(normalize_country(c), None)
        rr = region_rates.get(region, {"fixed_rate":0.02,"reg_rate":0.005,"opening_rate":0.03,"tax_rate":0.20})
        hi_pc_cap = p_max if remaining_cash is None else min(p_max, max(0.0, remaining_cash / max(pop,1.0)))
        best=None; best_cat=None; best_margin=None; best_mode=None; best_pen=None
        for cat, price_mult in price_cats:
            if abs(price_mult-2.4)<1e-6 and (ma_quantile>=0.0) and (c not in allow_ma):
                continue
            margin_pct = margin_from_price_mult(price_mult)
            # FDI
            mkt_pc_fdi, est_fdi = argmax_mkt_pc(pop, score, competitors, price_mult, margin_pct, epsilon, p_max, k, gamma_comp, score_mode,
                                                rr.get('fixed_rate',0.02), rr.get('reg_rate',0.005), rr.get('opening_rate',0.03), rr.get('tax_rate',0.20),
                                                True, comp_price, gdp_aff, eta_gap, eta_disc, lo=0.0, hi=hi_pc_cap, tol=1e-5)
            cand_est = est_fdi.copy(); cand_est["MKT_pc"]=mkt_pc_fdi; cand_est["Mode"]="FDI"; cand_est["PricePenalty"]=est_fdi["PricePenalty"]
            # JV
            mkt_pc_jv, est_jv = argmax_mkt_pc(pop, score, competitors, price_mult, margin_pct, epsilon, p_max, k, gamma_comp, score_mode,
                                              rr.get('fixed_rate',0.02), rr.get('reg_rate',0.005), rr.get('opening_rate',0.03)/2.0, rr.get('tax_rate',0.20),
                                              True, comp_price, gdp_aff, eta_gap, eta_disc, lo=0.0, hi=hi_pc_cap, tol=1e-5)
            est_jv_parent = est_jv.copy(); est_jv_parent["NetIncome"] *= 0.5; est_jv_parent["MKT_pc"]=mkt_pc_jv; est_jv_parent["Mode"]="JV"; est_jv_parent["PricePenalty"]=est_jv["PricePenalty"]
            choice = cand_est if cand_est["NetIncome"] >= est_jv_parent["NetIncome"] else est_jv_parent
            if (best is None) or (choice["NetIncome"] > best["NetIncome"]):
                best = choice.copy(); best_cat=(cat, price_mult); best_margin=margin_pct; best_mode=choice["Mode"]; best_pen=choice["PricePenalty"]
        if best is None: continue
        new_rows.append({
            "Country": c,
            "Competitors(Y+1)": int(competitors),
            "Score(0-100)": round(score,1),
            "GDPpc": gdppc,
            "Mode": best_mode,
            "PriceCat": best_cat[0],
            "Price_mult": best_cat[1],
            "Margin%": best_margin,
            "PricePenalty": best_pen,
            "MKT_pc": best["MKT_pc"],
            "MKT_total": best["MKT_pc"]*pop,
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

    return metrics, df_owned, df_new, cash_cap, owned, remaining_cash, comp_price, gdppc_median, epsilon

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
    ap.add_argument("--min_year", type=int, default=2008, help="Ignora anos anteriores (default=2008)")
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
    ap.add_argument("--list_sheets", action="store_true")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    if args.list_sheets:
        xls = pd.ExcelFile(args.xlsx)
        print("Abas encontradas:")
        for s in xls.sheet_names:
            print(" -", s)
        return

    metrics, df_owned, df_new, cash_cap, owned, remaining_cash, comp_price, gdppc_median, eps = decide_for_group(
        xlsx_path=args.xlsx, group=args.group, decision_year=args.decision_year, cash_cap_pct=args.cash_cap_pct,
        pop_sheet=args.pop_sheet, country_col=args.country_col, year_header_row=args.year_header_row,
        gdp_year_header_row=args.gdp_year_header_row, gdp_header_auto=args.gdp_header_auto, gdp_country_col=args.gdp_country_col,
        min_pop_m=args.min_pop_m, min_score=args.min_score, min_year=args.min_year,
        p_max=args.p_max, k=args.k, gamma_comp=args.gamma_comp, score_mode=args.score_mode,
        eta_gap=args.eta_gap, eta_disc=args.eta_disc, aff_alpha=args.aff_alpha, ma_quantile=args.ma_quantile,
        epsilon_override=args.epsilon_override, debug=args.debug
    )

    print(f"\n=== Grupo: {args.group} | Ano de decisão: {args.decision_year} (resultado em {args.decision_year+1} ) ===")
    if cash_cap is not None:
        print(f"Cap de MKT ( {int(args.cash_cap_pct*100)} % do caixa do ano): ~US$ {round(float(cash_cap),2)}")
    print(f"ε (elasticidade) usado: {eps:.3f} | Avg Competitor price (proxy): {comp_price:.3f} | GDPpc mediana: {gdppc_median:,.2f}")

    print("\nPaíses já presentes do grupo:", ", ".join([str(o).title() for o in owned]) if owned else "(nenhum)")

    print("\n--- JÁ PRESENTES (ótimo: preço, margem por categoria, MKT_pc) ---")
    if not df_owned.empty:
        cols = ["Country","Score(0-100)","GDPpc","Competitors(Y+1)","PriceCat","Price_mult","Margin%","PricePenalty","MKT_pc","MKT_total","Est_P","Est_ARPU","Est_Revenue","Est_NetIncome"]
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

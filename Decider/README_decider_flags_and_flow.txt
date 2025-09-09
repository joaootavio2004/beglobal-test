be_global_decider — Guia de Parâmetros e Fluxo de Decisão (v036o)
=================================================================

Resumo
------
Este documento descreve **todas as flags e parâmetros** do script `be_global_decider_v036o.py` e detalha
o **passo a passo do algoritmo de decisão**, alinhado ao fluxo de cálculo de receitas/custos da própria planilha do Be Global.


1) Como chamar (exemplo)
------------------------
PowerShell (uma linha):
python .\be_global_decider_v036o.py --xlsx ".\unprotect_Be Global - Decisões e Relatório - Diurno (1).xlsx" --group 4 --decision_year 2012 --cash_cap_pct 0.5 --pop_sheet "Population" --country_col "Name" --year_header_row 1 --gdp_header_auto --min_year 2008 --base_source demand --demand_sheet "Market Analyzes" --p_max 0.09 --k 150 --k_owned 30 --pmax_owned_mult 1.25 --gamma_comp 0.35 --score_mode sqrt --eta_gap 1.0 --eta_disc 0.20 --aff_alpha 0.60 --ma_quantile 0.8 --epsilon_override 0.9 --objective blended --alpha_blend 0.7 --rho_default 0.6 --min_pop_m 20 --price_override "United States:Médio,Canada:Médio" --lock_price_owned --min_mkt_owned_pc 0.008 --min_mkt_owned_total 6000000 --target_share "United States:0.05" --share_penalty 0.8 --debug


2) Parâmetros (flags) — o que fazem
------------------------------------

ARQUIVO E CONTEXTO
- --xlsx <path>              : Caminho do XLSX "Des decisões e Relatório". (Obrigatório)
- --group <n>                : Número do grupo (1..N). Usado para achar países já presentes e caixa.
- --decision_year <YYYY>     : Ano em que a decisão é tomada (ex.: 2012 → efeitos em 2013).
- --cash_cap_pct <0..1>      : Teto de marketing = % do caixa do ano (ex.: 0.5 → 50%).

SHEETS/MAPAS
- --list_sheets              : Lista as abas detectadas e sai.
- --pop_sheet <name>         : Aba com população/país/ano (padrão: "Population").
- --country_col <name>       : Nome da coluna de país na aba de população (ex.: "Name").
- --year_header_row <idx>    : Linha-cabeçalho do ano para a aba de população (0 ou 1, conforme seu arquivo).
- --gdp_header_auto          : Tenta detectar cabeçalho de anos na aba de GDP automaticamente.
- --min_year <YYYY>          : Ignora anos anteriores (ex.: 2008). Útil para não “sujar” o GDPpc com 1960+.
- --base_source <pop|demand> : Base de tamanho de mercado. 
                               pop    → usa População do ano seguinte como base;
                               demand → usa “Market Analyzes” (demanda por país) como base (recomendado).
- --demand_sheet <name>      : Nome da aba de demanda (padrão: "Market Analyzes").

ADOPÇÃO / MARKETING
- --p_max <0..0.2>           : Limite superior de penetração **por unidade** de marketing per capita.
                               (p.ex. 0.03 = 3% máx. adicional por unidade). Ajuste conforme empiria do jogo.
- --k <+>                    : Inclinação (sensibilidade) da curva de resposta a marketing para **novas entradas**.
- --k_owned <+>              : Inclinação para **países já presentes** (costuma ser menor para incentivar sustain).
- --pmax_owned_mult <+>      : Multiplicador do p_max para países já presentes (ex.: 1.25 = +25% de teto).
- --min_mkt_owned_pc <+>     : Piso de MKT per capita em países já presentes (ex.: 0.008).
- --min_mkt_owned_total <+>  : Piso de MKT total (US$) em países já presentes (ex.: 6_000_000).

CONCORRÊNCIA / SCORE / PREÇO
- --gamma_comp <+>           : Força do efeito de concorrência. Maior = mais “punitivo” quando há players.
- --score_mode <linear|sqrt> : Como usar o índice “Score(0–100)” do XLSX na resposta (linear ou suavizado √).
- --epsilon_override <+>     : Elasticidade-preço na demanda (↑ = preço alto pune mais a penetração).
- --price_override "País:Cat,País:Cat"
                            : Força a categoria de preço para países listados (ex.: "United States:Médio,Canada:Médio").
- --lock_price_owned         : Se presente, fixa o preço dos **já presentes** nas categorias do override (se fornecido).

ELASTICIDADE / ACESSIBILIDADE (GDPpc)
- --eta_gap <+>              : Peso da razão GDPpc/mediana no “affordability” (gap para cima/baixo).
- --eta_disc <+>             : Desconto aplicado quando GDPpc é abaixo da mediana (suaviza penalidade).
- --aff_alpha <0..1>         : Mistura affordability com penalidade de preço; ↑ = dá mais peso ao efeito de renda.

OBJETIVO DE OTIMIZAÇÃO
- --objective <profit|revenue|blended>
                            : Métrica para ranquear opções (lucro, receita ou mistura).
- --alpha_blend <0..1>       : Se “blended”, peso do lucro (1 = só lucro; 0 = só receita). Ex.: 0.7.

CARRY OVER / TAMANHO DE BASE
- --rho_default <0..1>       : Peso de carry no “tamanho efetivo” de mercados já presentes. Tipicamente 0.6.
- --min_pop_m <+>            : Filtra países com população/demanda efetiva abaixo de X milhões.

SHARE TARGET (empurrar share em ativos)
- --target_share "País:x.xx" : Objetivo de market share (por ex.: "United States:0.05" → 5%).
- --share_penalty <0..1>     : Penaliza soluções que fiquem abaixo do target no objetivo (0.8 = forte).

OUTROS
- --ma_quantile <0..1|-1>    : Ponto de corte usado ao normalizar macro/afins (0.8 = quantil 80%; -1 = desliga/usa mediana).
- --debug                    : Exibe diagnósticos (amostras GDP/Pop, medianas, etc.).


3) Passo a passo — como o script decide
---------------------------------------
A. **Leitura e mapeamento do XLSX**
   1. Lê **Population**, **GDP** e (se base=demand) **Market Analyzes**.
   2. Constrói um painel `macro_long` por país/ano.
   3. Calcula **GDPpc**. Se ausente/zero, faz *fallback*:
      GDPpc := (GDP(million US$)*1e6 / Population) / 1000.
      Se ainda assim faltar, usa a **mediana** do GDPpc observado para o ano.
   4. Obtém presença do seu grupo (países ativos) e **caixa** (General/Individual Report).
   5. Conta concorrentes por país/ano (para o **year+1**, isto é, o ano do resultado).

B. **Cap de Marketing (caixa)**
   6. Define **cap_total** = `cash_cap_pct * caixa_do_ano`.
   7. O bloco “já presentes” reserva MKT (respeitando `min_mkt_owned_pc` e/ou `min_mkt_owned_total`),
      o restante vira **caixa_remanescente** para “entradas novas”.

C. **Países já presentes (sustain/otimização local)**
   8. Para cada país ativo:
      - Fixa o **preço** por categoria (se `--lock_price_owned` e/ou `--price_override` foram usados).
      - Varre **mkt_pc** (per capita) acima de um piso (`min_mkt_owned_pc`) e otimiza
        o objetivo (lucro/receita/blended), com `k_owned` e `pmax_owned_mult`.
      - Aplica **competição** com `gamma_comp` e **affordability** via GDPpc (η_gap/η_disc).
      - Respeita **cap** mínimo em US$ (`min_mkt_owned_total`).
   9. Atualiza o **caixa_remanescente** (cap_total – MKT_alocados_em_ativos).

D. **Novas Entradas (1 país por rodada, mas lista top 3)**
  10. Para cada país-candidato (filtra por `min_pop_m` e não-ativos):
      - Para cada **categoria de preço** (Muito Baixo, Baixo, Médio, Alto, Muito Alto):
        *Define `price_mult` e **margem%** conforme a grade oficial.*
      - Avalia **FDI** e **JV**:
        *FDI* → abertura plena; *JV* → abertura/risco pela metade e **lucro final /2** (partner share).
      - Otimiza **mkt_pc** (0..p_max), mas **limitado pelo caixa_remanescente**.
      - Seleciona o modo (FDI/JV) com **melhor objetivo**.
  11. Ordena países/combos pelo objetivo e exibe os **Top 3**.

E. **Cálculo Econômico (respeitando o fluxo da planilha)**
  Para cada teste de (país, preço, margem, mkt_pc, modo):

  1) **Penetração / Adoção** (próximo ano):
     - *Curva de resposta a MKT* (forma logística/exp):
       P_raw = p_max_eff * (1 – exp(– k_eff * mkt_pc * Score_eff * PricePenalty * Affordability))
       • `p_max_eff` = p_max (novos) ou p_max*pmax_owned_mult (ativos)
       • `k_eff`     = k (novos) ou k_owned (ativos)
       • `Score_eff` = Score(0–100) (linear ou sqrt)
       • `PricePenalty` = (price_mult / avg_competitor_price)^(-epsilon)
       • `Affordability` = f(GDPpc/mediana; η_gap, η_disc) misturado via `aff_alpha`
     - **Competição**:
       comp_mult = 1 / (1 + gamma_comp * #competitors_year+1)
     - **Penetração final**: P = P_raw * comp_mult
     - **Clientes Ativos (ano+1)**: Q = P * Base_Tamanho
       • Base_Tamanho = População(Y+1) OU Demanda da "Market Analyzes" (se base=demand).
       • Para ativos, o carry pode ajustar levemente a base com `rho_default`.

  2) **Receita (“Your Revenues” na planilha)**
     - **ARPU / Preço**: ARPU = ARPU_base * price_mult
       (categorias de preço seguem a grade oficial da Config!: Muito Baixo -40%, Baixo -20%, Médio 0%, Alto +20%, Muito Alto +140%)
     - **Receita**: Revenue = Q * ARPU

  3) **Custos Operacionais** (aproxima o fluxo da planilha)
     - Marketing: MKT_total = mkt_pc * Base_Tamanho
     - Fixos/Regulatórios: 
       FixedCost   = fixed_rate * Revenue
       RegCost     = reg_rate   * Revenue
     - **Abertura** (apenas em entradas no ano): 
       OpeningCost = opening_rate * Revenue
       • Em **JV**, OpeningCost é **metade**.
     - **Lucro Operacional (EBIT)**: EBIT = Revenue – (MKT + Fixed + Reg + Opening)

  4) **Imposto**:
     - Tax = max(0, EBIT) * tax_rate

  5) **Lucro Líquido (Net Income)**:
     - NetIncome = EBIT – Tax
     - Em **JV**, aplica-se **partner share**: NetIncome *= 0.5

  *Obs.: os coeficientes (fixed_rate, reg_rate, opening_rate, tax_rate) vêm por região/ano, mapeados do XLSX;
  caso falte, o script usa valores padrão conservadores.*

  6) **Objetivo (ranking)**:
     - profit    → maximiza NetIncome
     - revenue   → maximiza Revenue
     - blended   → α*NetIncome + (1–α)*Revenue  (α = `alpha_blend`)

  7) **Target Share (opcional, só em ativos)**:
     - Se `--target_share "País:x"` e a solução fica abaixo de x, aplica penalização multiplicativa `share_penalty` no objetivo,
       empurrando mais MKT para esse país.


4) Boas práticas e faixas sugeridas
-----------------------------------
- Calibrar primeiro com:  --objective blended  --alpha_blend 0.6~0.8
- Preço/Margem: Para ativos, travar com `--price_override` + `--lock_price_owned` quando já se sabe o que funciona.
- Concorrência: `--gamma_comp 0.25~0.45` (↑ se o mercado “satura” muito com rivais).
- Resposta a MKT: `--k` 100–200 (novos) / `--k_owned` 20–50 (ativos) e p_max 0.02–0.10 (depende da rodada).
- GDPpc: usar `--min_year 2008` e `--gdp_header_auto` para manter o GDPpc coerente com os anos relevantes.
- Caixa: confirmar o caixa no “General Report” e alinhar `--cash_cap_pct` (50% costuma bater com regras do jogo).


5) Saídas — como ler
---------------------
- **JÁ PRESENTES**: mostra preço/margem aplicados, MKT_pc e MKT_total, e as métricas estimadas (P, ARPU, Receita, Lucro).
- **ENTRADA (Top 3)**: lista os 3 melhores países já com modo (JV/FDI), preço, margem, MKT_pc ótimo e métricas.
- No modo `--debug`, imprime amostras de GDP/Pop, mediana de GDPpc, preços médios de concorrente (proxy), etc.


6) Alinhamento com a planilha do Be Global
-------------------------------------------
O fluxo acima replica o encadeamento da planilha: **Preço → ARPU → Clientes Ativos → Receita → (Marketing + Fixos + Regulatórios + Abertura) → Imposto → Lucro**.
As categorias de preço e margens são as mesmas do jogo; JV/FDI respeitam abertura e partilha; competição e curva de MKT
foram calibradas a partir dos resultados observados (R1/R2). Quando um coeficiente está ausente no XLSX, o script aplica
valores padrão conservadores (documentados no código) — você pode refiná-los conforme avançam as rodadas.


7) Troubleshooting rápido
-------------------------
- GDPpc “0.00”: use `--gdp_header_auto` + `--min_year 2008`. O fallback calcula GDPpc a partir de GDP(million)/Pop.
- Indents/erros estranhos: garanta que está usando **v036o** (arquivo limpo).  
- Preço dos ativos não travou: faltou `--lock_price_owned` ou o país não foi escrito exatamente como no XLSX em `--price_override`.
- EUA “tímido”: use `--target_share "United States:0.05"` e ajuste `--share_penalty` (0.6–0.9) e `--k_owned`/`--pmax_owned_mult`.
- Quer priorizar receita vs lucro: mude `--objective` ou `--alpha_blend`.


FIM

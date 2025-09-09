
# Be Global — Decider (v0.2.2c)

Assistente para recomendar **investimentos por país** na simulação *Be Global*, maximizando **Lucro** (Net Income) sob **restrição de caixa**.  
Funciona a partir do seu arquivo **“Decisões e Relatório” (XLSX)** e lê: população, GDP, presença por país, resultados financeiros, MSE por região e configurações de preço.

> **Resumo:** para cada país (os que você já possui e os candidatos a entrar), o script procura a melhor **categoria de preço**, aplica a **margem** correspondente, e otimiza o **Marketing per capita (MKT_pc)**. Para novos países, compara **FDI vs JV**, respeita **concorrência** e **cap de caixa**.
>
> **Entrada anual:** o script pergunta o **ano da decisão** (Y). As recomendações valem para **Y+1**.

---

## Entradas (como o script lê seu XLSX)

- **Population** (aba): precisa ter os anos por colunas (ex.: 2009, 2010, 2011…).  
  - Flags: `--pop_sheet`, `--country_col`, `--year_header_row` (linha com os anos, tipicamente `1`).

- **GDP** (aba): layout como o de Population (mesmos países/anos).  
  - O script calcula **GDP per capita** (*GDPpc = GDP / Population*).  
  - **Se a mediana de GDPpc aparecer como 0.00**, é porque o GDP não foi parseado corretamente. Veja “Troubleshooting”.

- **Country Presence** (aba): detecta **entradas por time** (T1, T2, …) por **ano** e **modo** (FDI/JV).  
  - Usado para: **seu portfólio atual** (até o ano Y) e **contagem de concorrentes por país** (entradas até Y+1).

- **Result data** (aba): pega o seu **“Average Competitor price”** do ano Y (proxy global) e calibra a **elasticidade** ε (ver abaixo).

- **MSE per country** (aba): transforma a tabela em **taxas por região**:  
  - `fixed_rate`, `opening_rate`, `reg_rate`, `tax_rate` (todas frações da Receita).

- **Config!** (aba): categorias de preço (nome + multiplicador). Ex.:  
  - Muito Baixo ×0,6 / Baixo ×0,8 / Médio ×1,0 / Alto ×1,2 / Muito Alto ×2,4.

---

## Como o lucro é calculado

Para um país **c** e ano **Y+1**, dada população **Pop**, score de atratividade **S ∈ [0,100]**, número de concorrentes **C**, preço (**mult**) e MKT per capita (**p = MKT_pc**):

1) **Cap de penetração por score**  
   - `P_cap = p_max × f(S/100)` onde `f(x) = sqrt(x)` (padrão) ou `f(x) = x` (linear).  
   - Isso limita a penetração **mesmo com muito marketing**.

2) **Base de penetração por marketing e concorrência**  
   - `Base = (S/100) × p_max × (1 − exp(−k · p)) × (1 / (1 + γ · C))`  
   - `k` controla a **sensibilidade** do marketing; `γ` pune a presença de concorrentes.

3) **Penalização/bonificação por “gap de preço”**  
   - Lemos `comp_price` do seu **Average Competitor price** no ano Y.  
   - `ratio = mult / comp_price`  
   - **Se preço acima da concorrência:** `pen = exp(−η_gap · (ratio−1) / acessibilidade)`  
   - **Se preço abaixo:** `pen = exp(+η_disc · (1−ratio) · acessibilidade)`  
   - **Acessibilidade** vem do GDP per capita: `acessibilidade = (GDPpc / mediana_GDPpc)^α`, limitado aprox. a [0,3 .. 1,7].  
     País pobre ⇒ acessibilidade **menor** ⇒ **penalização maior** quando o preço é mais alto que o concorrente.

4) **Penetração efetiva**  
   - `P = min(P_cap, Base) × pen`

5) **ARPU (efeito de preço)**  
   - `ARPU = mult × rides_base × mult^{−ε} = rides_base × mult^{(1−ε)}`  
   - `ε` (elasticidade) é calibrado do seu `Your price`, `Your Revenues`, `Your Active Customers` via regressão em log-log.  
     Se preferir, force manualmente com `--epsilon_override`.

6) **Receita e custos**  
   - `Revenue = Pop × P × ARPU`  
   - **Margem bruta:** cada **categoria de preço** tem margem fixa:  
     - ×0,6→10%, ×0,8→20%, ×1,0→25%, ×1,2→30%, ×2,4→40%  
     - `MB = Revenue × Margin%`  
   - **Marketing:** `MKT_total = Pop × p`  
   - **Fixos:** `Fixed = fixed_rate × Revenue`  
   - **Reg./político:** `RegPol = reg_rate × Revenue`  
   - **Abertura (apenas no ano de entrada):** `Opening = opening_rate × Revenue`  
     - **FDI:** aplica 100% de Opening, lucro 100% para a matriz.  
     - **JV:** aplica **50%** de Opening, **50%** do lucro fica com a matriz.

7) **Impostos e lucro**  
   - `EBIT = MB − MKT_total − Fixed − RegPol − Opening`  
   - `Taxes = max(0, tax_rate × EBIT)`  
   - `NetIncome = EBIT − Taxes`

---

## Otimizações feitas pelo script

- **Países já presentes**: para cada país, varre **todas as categorias de preço** (e suas margens), e otimiza **MKT_pc** (busca da seção áurea em `[0, p_max]`).  
- **Novos países**: idem, mas compara **FDI vs JV** e respeita o **cap de caixa remanescente**.  
- **Cap de caixa global**: primeiro alocamos nos **países já presentes**. Se extrapolar o cap, **reescalamos** proporcionalmente. O que sobrar vai para a **entrada**.

---

## Parâmetros principais (CLI)

- **Arquivos / parsing**
  - `--xlsx` (obrigatório): seu “Decisões e Relatório”.  
  - `--pop_sheet` (default: `Population`)  
  - `--country_col` (default: `Name`)  
  - `--year_header_row` (default: `1`)  
  - `--list_sheets` (só lista abas e sai)

- **Restrições / filtros**
  - `--cash_cap_pct` (default: `0.50`) → % do caixa a gastar em MKT.  
  - `--min_pop_m` (default: `10`) → população mínima (em milhões) p/ candidatos.  
  - `--min_score` (default: `15`) → score mínimo p/ candidatos.

- **Penetração e concorrência**
  - `--p_max` (default: `0.03`) → teto teórico (se `score=100%`). **Calibra com R1/R2**.  
  - `--k` (default: `120`) → sensibilidade do marketing.  
  - `--gamma_comp` (default: `0.30`) → penalização por concorrentes.  
  - `--score_mode` (`sqrt`|`linear`, default: `sqrt`) → teto mais brando em scores baixos.

- **Preço x concorrente x renda**
  - `--eta_gap` (default: `0.75`) → severidade quando seu preço está **acima** do competidor.  
  - `--eta_disc` (default: `0.25`) → bônus quando **abaixo**.  
  - `--aff_alpha` (default: `0.50`) → peso da acessibilidade (GDPpc vs mediana).  
  - `--ma_quantile` (default: `0.60`) → só permite **×2,4** em países **acima** desse quantil de GDPpc. Use `-1` para **desligar** o gate.

- **Elasticidade**
  - `--epsilon_override` (sem default): força ε (0,3–1,2 costuma ser razoável). Se não passar, o script calibra do seu `Result data`.

---

## Calibração sugerida (para aproximar R1/R2)

1) **Ajuste p_max e k** para bater a penetração observada (ex.: EUA ~ 3,951M usuários em ~311M hab. ⇒ ~**1,27%**).  
   - Comece com: `--p_max 0.09 --k 150` (mais teto e um pouco mais de sensibilidade).

2) **Elasticidade**: se o script insiste em preço “Muito Alto”, **suba ε** (maior sensibilidade a preço).  
   - Ex.: `--epsilon_override 0.9` (ARPU cresce pouco com preço).

3) **Penalização de prêmio**: aumente `--eta_gap` e reduza `--eta_disc`.  
   - Ex.: `--eta_gap 1.0 --eta_disc 0.20`.

4) **Gate ×2,4** (opcional): depois que **GDPpc** estiver OK, use `--ma_quantile 0.8` para restringir ×2,4 a países ricos.  
   - Enquanto o GDPpc não parsear direito (mediana **0.00**), **desligue** o gate: `--ma_quantile -1`.

**Comando recomendado (teste):**
```powershell
python .\be_global_decider.py ^
  --xlsx ".\unprotect_Be Global - Decisões e Relatório - Diurno (1).xlsx" ^
  --group 4 ^
  --decision_year 2012 ^
  --cash_cap_pct 0.5 ^
  --pop_sheet "Population" --country_col "Name" --year_header_row 1 ^
  --p_max 0.09 --k 150 --gamma_comp 0.35 --score_mode sqrt ^
  --eta_gap 1.0 --eta_disc 0.20 --aff_alpha 0.60 --ma_quantile -1 ^
  --epsilon_override 0.9
```

---

## Troubleshooting (especial G**DPpc mediana = 0.00**)

Se `GDPpc` sair 0 (ou NaN) e a mediana mostrar **0.00**, o parse do GDP falhou. Causas comuns:
- Números são strings com separadores (ponto/vírgula/espaço), unidades (“billions”), ou outra linha de cabeçalho.

**Soluções rápidas:**
- Verifique se `--year_header_row` vale **1** também para a aba **GDP** (no seu arquivo, costuma ser o mesmo da Population).  
- Se mesmo assim der 0, use temporariamente `--ma_quantile -1` (desliga o gate ×2,4).  
- Opcional: ajuste manualmente a elasticidade `--epsilon_override`.

**Patch de robustez para GDP (se quiser editar o código):**
No método que lê GDP, aplique uma limpeza antes do `to_numeric`, por exemplo:
```python
s = str(raw).strip()
s = s.replace('\xa0',' ').replace(',','').replace(' ','')
s = re.sub(r'[^0-9.\-]','',s)
val = pd.to_numeric(s, errors='coerce')
```
E garanta que a coluna de país e as colunas de anos estão corretas (mesmo `year_header_row` da Population).

---

## Saída — o que significam as colunas

- **Score(0-100)**: índice de atratividade (população + GDPpc normalizados).  
- **Competitors(Y+1)**: número de times que entraram até Y+1.  
- **PriceCat / Price_mult**: categoria e multiplicador de preço usado.  
- **Margin%**: margem correspondente à categoria (0,6→10%, 0,8→20%, 1,0→25%, 1,2→30%, 2,4→40%).  
- **PricePenalty**: multiplicador aplicado à **penetração P** por conta do **gap de preço** e **GDPpc**.  
- **MKT_pc / MKT_total**: marketing per capita e valor total (Pop × MKT_pc).  
- **Est_P**: penetração estimada.  
- **Est_ARPU**: receita média por usuário.  
- **Est_Revenue / Est_NetIncome**: receita e lucro estimados.

---

## Changelog (resumo)

- **v0.2.1** — margem por categoria de preço; `score_mode sqrt` (menos punitivo em scores baixos).  
- **v0.2.2** — penalização por **gap de preço** vs concorrente; **acessibilidade por GDPpc**; gate de **×2,4** por quantil.  
- **v0.2.2a/b/c** — correções de **índices duplicados** e **GDPpc**; dedup seguro; README.

---

## Licença e uso
Código para uso acadêmico na disciplina, sem garantias. Ajuste os parâmetros conforme seus dados reais (R1/R2) e valide contra o simulador.

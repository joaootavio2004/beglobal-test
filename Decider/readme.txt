--xlsx (o seu arquivo de decisões e relatório)

--group (ex.: 4)

--decision_year (ex.: 2012 → o resultado vale para 2013)

--cash_cap_pct (padrão 0.50 para respeitar o teto de marketing)



python .\be_global_decider.py `
  --xlsx ".\unprotect_Be Global - Decisões e Relatório - Diurno (1).xlsx" `
  --group 4 `
  --decision_year 2012 `
  --cash_cap_pct 0.5 `
  --pop_sheet "Population" `
  --country_col "Country"
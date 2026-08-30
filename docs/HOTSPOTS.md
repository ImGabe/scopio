# 🔥 Scopio Hotspots — Análise de Risco e Código Crítico

O **Scopio Hotspots** identifica os arquivos de maior risco técnico no seu codebase cruzando **Complexidade Ciclomática (CCN)** com a **Frequência de Modificações (Churn)**.

---

## 🎯 Por que calcular Hotspots?

Em projetos de software:
- Um arquivo altamente complexo que **nunca muda** representa baixo risco no dia a dia.
- Um arquivo altamente complexo alterado com **alta frequência** é a maior fonte de regressões e bugs da equipe.

---

## 🚀 Como usar o `scopio hotspots`

No seu terminal ou CI/CD:

```bash
# Exibir o ranking dos 10 maiores hotspots
scopio hotspots

# Especificar um projeto e limite de resultados
scopio hotspots --project scopio --limit 5

# Exportar em formato JSON ou Markdown
scopio hotspots --format json
scopio hotspots --format markdown
```

---

## 📊 Fórmula de Score e Níveis de Risco

$$\text{Hotspot Score} = \text{MaxCCN} \times \left(1 + \log_2(\text{Audit Changes} + 1)\right) + (\text{Warnings} \times 1.5)$$

- 🔥 **HIGH RISK** (Score $\ge 30.0$): Código prioritário para refatoração e testes.
- ⚠️ **MEDIUM RISK** (Score $\ge 15.0$): Requer atenção e revisão contínua.
- ℹ️ **LOW RISK** (Score $< 15.0$): Baixa frequência de alterações ou baixa complexidade.

# Decisões de Arquitetura e Escopo — scopio

> Status: **aprovado** · Data: 2026-08-29
> Este documento consolida as decisões tomadas a partir de:
> - Revisão externa do código (feedback de IA que usou o scopio em projeto Rust real).
> - Exploração do ecossistema do boyter (scc, cs, lc, dcd, searchcode.com).
> - Discussão técnica entre duas IAs sobre o desenho do hub de adaptadores.
>
> Cada item está classificado como **implementar**, **não implementar** (com motivo) ou **já implementado**.

---

## 1. Contexto

O scopio nasceu como uma CLI Python que audita projetos usando `scc` (LOC/linguagens) e `lizard` (complexidade), com histórico em SQLite. A revisão externa apontou problemas estruturais (gate de CCN por média, `ci` com exit code mentindo, `warnings` sempre 0, diff comparando 1ª com última auditoria). Some-se o risco de depender de binários com roadmap alheio (scc 4.x com hotspots enquanto o scopio travava em `>=3.3,<4.0`).

Pergunta estratégica: **o scopio ainda faz sentido e qual arquitetura deve ter?**

---

## 2. Identidade (o que o scopio É)

- **Auditor estrutural leve com histórico + gates de CI.** Não é orquestrador de linters (MegaLinter), nem plataforma de code intelligence (searchcode), nem buscador de código.
- **Reaproveita o ecossistema do usuário**: usa as ferramentas que o projeto auditado já integra (linters nativos e linters do próprio CI), sem exigir instalação de ferramentas "do scopio" nem reimplementar contadores.
- **Camada `collect/` (hub de adaptadores)** como porta única de fontes de dados, separando o que o scopio **executa** do que ele apenas **lê**.

---

## 3. Decidido implementar

### 3.1 Arquitetura do hub (`collect/`)

| Item | Decisão | Detalhe |
|---|---|---|
| `collect/run/` | Executa ferramentas **leves** de métricas | `scc`, `lizard`, `git`; futuros `dcd` (duplicação) e ingestão de `scc --hotspots` (churn). Rápidas, analisam texto/AST, não compilam. |
| `collect/ingest/` | Lê relatórios **SARIF** de linters pesados | Rust (clippy), JS/TS (eslint), Python (ruff), Go (golangci-lint). O scopio **não executa** o linter: o pipeline do usuário gera o `.sarif` e o scopio apenas consome. |
| Contrato normalizado | Engine consome **um** contrato granulado | `{source, file, rule, severity, message}` — nunca o formato cru do linter. Tipos em `TypedDict` (consistente com `scopio/types.py`). |

### 3.2 Ingestão SARIF (estrita)

- **SARIF-only**: aceita **exclusivamente** SARIF v2.1.0. Ferramentas sem SARIF nativo (clippy, eslint) são convertidas na esteira do CI do usuário (`clippy-sarif`, `@microsoft/eslint-formatter-sarif`), antes do scopio rodar.
- **Normalização de caminhos obrigatória** em todo `physicalLocation.artifactLocation.uri`: remover `file://`, resolver absolutos contra `proj_path`, forçar POSIX `/`, e classificar arquivos fora da raiz (deps, `node_modules`, `~/.cargo/`) como `external` (ignorados no gate por arquivo).
- **Estados explícitos por fonte**: `clean` (rodou, zero achados), `violations` (rodou, tem achados), `not_run` (relatório ausente / tool indisponível). **`not_run` NUNCA equivale a "0 warnings"** — lição herdada do bug do `ci` exit-0.
- **Modes**: fonte declarada em `[ingest.sources.<id>]` tem default **`required`** (ausência → `not_run` → falha o gate). `optional` é explícito para adoção gradual e nunca vira "passou limpo".
- **Transparência**: estado de cada fonte visível no payload `observability` da auditoria.

### 3.3 Métricas e gates de warnings

- **Nada de `warnings: int` único** (vira teatro: 1 aviso crítico do clippy ≠ 1 aviso de estilo do eslint). Contrato granulado + gate por severidade/regra.
- **Mapeamento de severidade** a partir do `result.level` nativo do SARIF: `error` → ERROR, `warning` → WARNING, `note`/`none` → INFO.
- **Override por regra** (`[ingest.rules_override]`): reclassificar/ignorar regras independente do linter original (ex.: `"clippy::needless_return" = "ignore"`).
- **Gate em duas camadas** (`[quality_gates.ingest]`): `max_errors`, `max_warnings` (tetos globais) + `blocked_rules` (falha imediata por regra específica).
- **Armazenamento em duas camadas** (evitar inchar o SQLite):
  - **Persistente**: tabela `audit_ingest_summary(audit_id, source_id, file_path, severity, count)` — série temporal leve.
  - **Transitório**: `findings` granulares (rule_id, message) usados na auditoria/relatório daquele run, sem inflar o histórico.

### 3.4 Fases de entrega (roadmap)

| Milestone | Escopo | Issue |
|---|---|---|
| **0.4.0** | Refactor interno: criar `scopio/collect/run/` + contratos normalizados (migrar scc/lizard/git). **Sem mudança de comportamento** — testes verdes. | #1 |
| **0.4.1** | Módulo de ingestão SARIF: parser estrito + normalização de caminhos + estados/modes + tabela de sumário. | #2 |
| **0.5.0** | Gates + CLI: severidade, `rules_override`, `max_errors`/`max_warnings`/`blocked_rules`, observability, cookbook. | #3 |
| **Backlog** | `scopio hotspots` nativo · suporte scc 4.x · `report --format json` · top offenders · exports configuráveis | #10, #8, #6, #7, #9 |

---

## 4. Decidido NÃO implementar (e por quê)

| # | O que NÃO fazer | Motivo |
|---|---|---|
| 1 | **Reimplementar scc/lizard** (contadores multi-linguagem) | 250+ linguagens com anos de edge-cases; reimplementar é meses/anos de trabalho com resultado pior (confirmado por `docs/SPIKE_REPORT.md`). |
| 2 | **Executar linters pesados a partir do scopio** (`cargo clippy`, `eslint`, `golangci-lint`) | Compilam/resolvem dependências/travam `target/`; falham ou travam em CI limpo. Escopo do scopio não é rodar isso. |
| 3 | **Manter conversores JSON por linter dentro do scopio** | Schemas instáveis (NDJSON do clippy; eslint v8↔v9↔v10) = manutenção infinita. Converter na esteira do usuário. |
| 4 | **Agregar warnings em inteiro único** | Incomparável entre ferramentas (2 erros críticos ≠ 50 avisos de estilo); vira teatro de métrica. |
| 5 | **Fallback silencioso (0/None) quando a ferramenta falta** | Repete o bug do `ci` exit-0 (gate aprovaria "limpo" sem nada rodar). Estado é `not_run` explícito; fonte `required` faltando **falha**. |
| 6 | **Virar orquestrador de linters** (MegaLinter, Trunk.io, SonarQube) | Escopo diferente; transformaria o scopio em mantenedor de N adaptadores de CLI de terceiros. |
| 7 | **Competir com busca/duplicação/licença do boyter** (`cs`, `dcd`, `lc`, searchcode) | Já são maduros; o nicho do scopio é série temporal + multi-projeto + gates — não busca/análise one-shot. |
| 8 | **Depender do pacote PyPI `scc`** | O PyPI `scc` é OUTRA ferramenta (ome/scc); o correto é o binário/go install do `boyter/scc`. Já documentado no README. |
| 9 | **Reimplementar o ecossistema completo num one-binary (rota boyter)** | Custo altíssimo; o scopio não precisa ser dono das primitivas — precisa ser dono da **costura** (camada de adaptadores). |

---

## 5. Já implementado (0.2.2 / 0.3.0)

| Item | Status |
|---|---|
| `ci` retornava exit 0 com status "failed" | ✅ exit code espelha o status — 0.2.2 |
| Validação de versão (major/minor exato em vez de range) | ✅ validação por range — 0.2.2 |
| Gate de CCN usava só média (perdia outliers) | ✅ `ccn_max` + `max_function_ccn` — 0.3.0 |
| `ccn_max` era coluna morta | ✅ rastreado em db/histórico/exports/report — 0.3.0 |
| `diff` comparava 1ª com última | ✅ anterior→atual + `--base first` — 0.3.0 |
| `file_metrics` por função confundia diff-report | ✅ agregado por arquivo (NLOC soma, CCN max) — 0.3.0 |
| `CI_RULES` marcava "LOC decreased"/"CCN regressed" como failure | ✅ removidas + thresholds configuráveis — 0.3.0 |
| `warnings` sempre 0 no parser CSV do lizard | ✅ documentado como 0; resolução definitiva = ingestão SARIF (#2/#3) |
| `_fs_sharp_fallback` (hack F# por subprocess) | 📌 a migrar para ingestão |
| Armadilha do `pip install scc` | ✅ troubleshooting documentado — 0.2.2 |
| `_parse_lizard_output` (código morto) | ✅ removido — 0.3.0 |

Fora da review, também entrou: fluxo de commit (Commitizen + pre-commit + Conventional Commits), pipeline de publish (build → twine check → aprovação manual → PyPI), e mypy alinhado ao CI.

---

## 6. Referências

- **Backlog/kanban**: GitHub Projects `scopio` — https://github.com/users/ImGabe/projects/1 (issues #1–#10)
- **Spike de dependências nativas**: `docs/SPIKE_REPORT.md` (radon/pygount "não viável" p/ substituir scc/lizard)
- **Hotspots**: post do boyter sobre scc 4.0 `--hotspots` / `--coupling`

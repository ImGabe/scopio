# Decisões de Arquitetura e Escopo — scopio

> Status: **aprovado** · Data: 2026-08-29 (Revisado com as 5 Diretrizes de Ouro)
> Este documento consolida as decisões tomadas a partir de:
> - Revisão externa do código e análise de usabilidade/DX.
> - Análise de viabilidade para eliminação de atrito e overengineering.
> - Admoestação das 5 Diretrizes de Ouro: Zero-Config, Ingestão Flexível (JSON Nativo + SARIF), CLI Human-First, Diff Uncommitted e Manutenção Simples.

---

## 1. Contexto

O scopio nasceu como uma CLI Python que audita projetos usando `scc` (LOC/linguagens) e `lizard` (complexidade), com histórico em SQLite. A revisão de arquitetura apontou que impor conversores SARIF externos trazia alta fricção de DX e que tentar gerenciar regras de linters dentro do scopio era overengineering.

Pergunta estratégica: **Como manter o scopio extremamente útil, leve e sem atrito para o desenvolvedor?**

---

## 2. Identidade e as 5 Diretrizes de Ouro

1. **Usabilidade Zero-Config**: Leitura automática do `.gitignore`, `--project` opcional quando houver 1 único projeto, e diagnóstico via `scopio doctor`.
2. **Ingestão sem Fricção**: Suporte nativo a JSONs dos linters populares (Ruff, ESLint, Clippy) + SARIF v2.1.0 como fallback universal.
3. **CLI Human-First**: Saídas em tabelas formatadas e legíveis no terminal por padrão, reservando JSON cru para `--json` ou ambiente de CI.
4. **Diff de Código Não-Commitado**: Suporte a `scopio diff --dirty` / `--uncommitted` para feedback pré-commit rápido.
5. **Manutenibilidade e Core Enxuto**: Foco em métricas estruturais (LOC, NLOC, CCN) + 3 severidades de warnings (`errors`, `warnings`, `info`), sem sobrecarregar o scopio como orquestrador de linters.

---

## 3. Decidido Implementar

### 3.1 Arquitetura do hub (`collect/`)

| Item | Decisão | Detalhe |
|---|---|---|
| `collect/run/` | Executa ferramentas **leves** de métricas | `scc`, `lizard`, `git`. Rápidas, analisam texto/AST, não compilam. |
| `collect/ingest/` | Lê relatórios de linters | **JSON nativo** (Ruff, ESLint, Clippy) e **SARIF v2.1.0** para outros linters. O scopio **não executa** o linter. |
| Contrato normalizado | Engine consome **um** contrato granulado | `{source, file, rule, severity, message}`. Tipos em `TypedDict` em `scopio/types.py`. |

### 3.2 Melhorias de UX e DX

- **`--project` opcional**: Quando `projects = ["."]` ou houver apenas 1 projeto no `scopio.toml`, o Scopio assume o projeto sem exigir `--project`.
- **Suporte nativo ao `.gitignore`**: Uso de `pathspec` para ignorar arquivos definidos no `.gitignore` sem necessidade de re-cadastrá-los no `scopio.toml`.
- **Diagnóstico via `scopio doctor`**: Comando que checa a disponibilidade de `scc`, `lizard`, `git` e exibe instruções amigáveis em caso de ausência.
- **`scopio diff --dirty`**: Comparação das métricas do working tree atual (código não-commitado) contra a última auditoria do banco SQLite.

### 3.3 Fases de entrega (Roadmap Revisado)

| Milestone | Escopo | Foco Principal |
|---|---|---|
| **0.3.1** | **Fixes de Usabilidade & DX Immediate**: Fix no teste Parquet (mock `sys.modules`), agregação por arquivo no `_parse_lizard_csv`, `--project` opcional, `.gitignore` nativo via `pathspec`, e comando `scopio doctor`. | Estabilidade e Usabilidade |
| **0.4.0** | **Hub `collect/` & Diff Dirty**: Refatoração interna `scopio/collect/`, ingestão de JSON nativo (Ruff/ESLint/Clippy) + SARIF fallback, comando `scopio diff --dirty`, e tabelas formatadas para CLI. | Ingestão Flexível & Work-in-Progress |
| **0.5.0** | **Gates de CI & Automação**: Gates por severidade (`max_errors`, `max_warnings`), e `scopio ci --format github-comment` para comentários em PRs. | CI Automation |

---

## 4. Decidido NÃO Implementar (e por quê)

| # | O que NÃO fazer | Motivo |
|---|---|---|
| 1 | **Exigir conversores SARIF para tudo** | Adiciona fricção de DX massiva no pipeline do usuário. Linters populares devem ter ingestão JSON nativa. |
| 2 | **Motor complexo de `rules_override` por regra** | Overengineering. Linters já gerenciam suas próprias regras; o scopio só aplica gates por severidade (`max_errors`, `max_warnings`). |
| 3 | **Executar linters ou compiladores pesados a partir do scopio** | Mantém o scopio leve e rápido. Ele apenas consome os relatórios gerados. |
| 4 | **Agregar warnings em inteiro único** | Incomparável entre ferramentas. Agrupar obrigatoriamente por severidade (`errors`, `warnings`, `info`). |
| 5 | **Descartar mensagens de `findings` no histórico** | Mantém os `findings` (regra + arquivo) no SQLite para que o `diff-report` possa listar quais avisos novos surgiram. |

---

## 5. Status Atual (0.3.0)

| Item | Status |
|---|---|
| Fix no teste de Parquet | ⌛ A ser feito na 0.3.1 |
| Agregação de `file_metrics` por arquivo único | ⌛ A ser feito na 0.3.1 |
| `--project` opcional | ⌛ A ser feito na 0.3.1 |
| Integração nativa `.gitignore` | ⌛ A ser feito na 0.3.1 |
| `scopio doctor` | ⌛ A ser feito na 0.3.1 |
| Gate de CCN com `ccn_max` e `max_function_ccn` | ✅ Implementado na 0.3.0 |
| Histórico SQLite e Diffs com `--base first` | ✅ Implementado na 0.3.0 |
Gabe/projects/1 (issues #1–#10)
- **Spike de dependências nativas**: `docs/SPIKE_REPORT.md` (radon/pygount "não viável" p/ substituir scc/lizard)
- **Hotspots**: post do boyter sobre scc 4.0 `--hotspots` / `--coupling`

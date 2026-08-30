# 📖 Scopio Ingestion Cookbook

Guia prático de como gerar relatórios de linters e ferramentas estáticas no CI/CD e ingeri-los nativamente no **Scopio**.

---

## 🛠️ 1. Configurando o `scopio.toml`

Adicione a seção `[ingest]` ao seu arquivo de configuração `scopio.toml`:

```toml
[discovery]
projects = ["."]

[ingest]
sources = [
    { name = "ruff", path = "reports/ruff.json" },
    { name = "eslint", path = "reports/eslint.json" },
    { name = "clippy", path = "reports/clippy.json" },
    { name = "sarif", path = "reports/security.sarif" }
]

[quality_gates.ingest]
max_errors = 0      # Reprova se houver qualquer erro de sintaxe/segurança
max_warnings = 15   # Limite máximo tolerado de avisos
```

---

## 🐍 2. Python (Ruff)

Gere o relatório em formato JSON com o `ruff`:

```bash
# Execução local ou no GitHub Actions
ruff check --output-format json src/ > reports/ruff.json
```

---

## ⚡ 3. JavaScript / TypeScript (ESLint)

Gere o relatório formatado em JSON com o `eslint`:

```bash
# Execução local ou no GitHub Actions
npx eslint src/ -f json -o reports/eslint.json
```

---

## 🦀 4. Rust (Clippy)

Gere a mensagem de compilação em formato JSON linhas (`NDJSON`):

```bash
# Execução local ou no GitHub Actions
cargo clippy --message-format=json > reports/clippy.json
```

---

## 🛡️ 5. SARIF Universal (CodeQL / Trivy / Semgrep / Bandit)

Qualquer ferramenta de análise de segurança compatível com a especificação **SARIF v2.1.0** pode ser inserida:

```bash
# Exemplo com Bandit (Python Security)
bandit -r src/ -f sarif -o reports/security.sarif
```

---

## 🚀 6. Executando a Auditoria com Ingestão

Com os relatórios gerados na pasta do projeto, execute o Scopio:

```bash
scopio run
```

O Scopio lerá as contagens de violações, aplicará os Quality Gates de severidade (`max_errors` e `max_warnings`) e salvará o histórico de cada arquivo no SQLite `.scopio/scopio.db`.

# Makefile — Aegis Desk
# Comandos frecuentes para desarrollo y verificación local.
# Usa .venv/bin/python si existe; si no, cae a python3 (util en CI).

PYTHON_BIN := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
PYTHON := PYTHONPATH=$$PWD $(PYTHON_BIN)

.PHONY: help test compile frontend evals redteam verify full clean install-hooks

help: ## Muestra esta ayuda
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

test: ## Corre tests deterministas (pytest)
	$(PYTHON) -m pytest tests/ -q

compile: ## Verifica sintaxis con compileall
	$(PYTHON_BIN) -m compileall -q src evals redteam scripts

frontend: ## Instala dependencias, lint y build del frontend
	cd frontend && npm install && npm run lint && npm run build

evals: ## Corre suite de evaluaciones (requiere API keys)
	$(PYTHON_BIN) -m evals.run_evals --save

retrieval-evals: ## Mide recall@k/MRR del retriever (sin LLM)
	DEEPINFRA_API_KEY= DATABASE_URL= SUPABASE_URL= SUPABASE_KEY= SUPABASE_SERVICE_KEY= PINEONE_API_KEY= $(PYTHON) -m evals.run_retrieval_evals --save

redteam: ## Corre suite de red teaming (requiere API keys)
	$(PYTHON_BIN) -m redteam.run_redteam --save

verify: test compile frontend ## Verificación local rápida: tests + compile + frontend
	@echo "✅ verify local completo. Ejecuta 'make evals' y 'make redteam' para suites con LLM."

full: verify evals redteam ## Verificación completa incluyendo evals/redteam
	$(PYTHON_BIN) scripts/verify_all.py

install-hooks: ## Instala el pre-commit hook de Git
	install -m 755 scripts/pre-commit.sh .git/hooks/pre-commit
	@echo "Pre-commit hook instalado en .git/hooks/pre-commit"

clean: ## Limpia resultados y cachés generados
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete

# Makefile — Aegis Desk
# Comandos frecuentes para desarrollo y verificación local.

VENV := .venv/bin
PYTHON := PYTHONPATH=$$PWD $(VENV)/python

.PHONY: help test compile frontend evals redteam verify full clean

help: ## Muestra esta ayuda
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

test: ## Corre tests deterministas (pytest)
	$(PYTHON) -m pytest tests/ -q

compile: ## Verifica sintaxis con compileall
	$(VENV)/python -m compileall -q src evals redteam scripts

frontend: ## Instala dependencias, lint y build del frontend
	cd frontend && npm install && npm run lint && npm run build

evals: ## Corre suite de evaluaciones (requiere API keys)
	$(VENV)/python -m evals.run_evals --save

redteam: ## Corre suite de red teaming (requiere API keys)
	$(VENV)/python -m redteam.run_redteam --save

verify: test compile frontend ## Verificación local rápida: tests + compile + frontend
	@echo "✅ verify local completo. Ejecuta 'make evals' y 'make redteam' para suites con LLM."

full: verify evals redteam ## Verificación completa incluyendo evals/redteam
	$(VENV)/python scripts/verify_all.py

install-hooks: ## Instala el pre-commit hook de Git
	install -m 755 scripts/pre-commit.sh .git/hooks/pre-commit
	@echo "Pre-commit hook instalado en .git/hooks/pre-commit"

clean: ## Limpia resultados y cachés generados
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete

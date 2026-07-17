#!/bin/bash
# Pre-commit hook para Aegis Desk.
# Corre tests deterministas y compileall antes de permitir el commit.
#
# Instalación:
#   cp scripts/pre-commit.sh .git/hooks/pre-commit
#   chmod +x .git/hooks/pre-commit

set -e

echo "==> Pre-commit: running make verify"
make verify

echo "==> Pre-commit: OK"

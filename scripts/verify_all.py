"""Verificación local completa de Aegis Desk.

Corre tests, compileall, frontend build y opcionalmente revisa los últimos
reportes de evals/redteam contra sus umbrales baseline.

Uso:
    .venv/bin/python scripts/verify_all.py --full   # incluye evals/redteam si existen reportes
    .venv/bin/python scripts/verify_all.py          # rápido: tests + compile + frontend
"""

import argparse
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def run(cmd: list[str], env: dict | None = None, cwd: Path | None = None) -> int:
    """Ejecuta un comando e imprime la salida."""
    print(f"\n$ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd or REPO, env={**os.environ, **(env or {})})
    return result.returncode


def check_compile() -> int:
    return run([sys.executable, "-m", "compileall", "-q", "src", "evals", "redteam", "scripts"])


def check_tests() -> int:
    env = {"PYTHONPATH": str(REPO)}
    return run([sys.executable, "-m", "pytest", "tests/", "-q"], env=env)


def check_frontend() -> int:
    frontend = REPO / "frontend"
    npm_install = run(["npm", "install"], cwd=frontend)
    if npm_install != 0:
        return npm_install
    lint = run(["npm", "run", "lint"], cwd=frontend)
    if lint != 0:
        return lint
    return run(["npm", "run", "build"], cwd=frontend)


def load_latest_report(pattern: str) -> dict | None:
    files = sorted(glob.glob(str(REPO / pattern)))
    if not files:
        return None
    try:
        return json.loads(Path(files[-1]).read_text())
    except Exception:
        return None


def check_evals_baseline() -> int:
    report = load_latest_report("evals/results/*report*.json")
    if not report:
        print("⚠️  No se encontró reporte de evals. Saltando chequeo de baseline.")
        return 0
    pass_rate = report.get("pass_rate") or report.get("score")
    baseline = report.get("baseline", {}).get("pass_rate", 1.0)
    print(f"Evals pass_rate={pass_rate} baseline={baseline}")
    if pass_rate is not None and pass_rate < baseline:
        print("❌ Evals por debajo del baseline")
        return 1
    print("✅ Evals OK")
    return 0


def check_redteam_baseline() -> int:
    report = load_latest_report("redteam/results/redteam_report_*.json")
    if not report:
        print("⚠️  No se encontró reporte de redteam. Saltando chequeo de baseline.")
        return 0
    defense_rate = report.get("defense_rate")
    baseline = report.get("baseline", {}).get("defense_rate", 1.0)
    print(f"Redteam defense_rate={defense_rate} baseline={baseline}")
    if defense_rate is not None and defense_rate < baseline:
        print("❌ Redteam por debajo del baseline")
        return 1
    print("✅ Redteam OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Verificación completa de Aegis Desk")
    parser.add_argument(
        "--full", action="store_true", help="Incluye chequeo de baseline de evals/redteam"
    )
    args = parser.parse_args()

    checks = [
        ("compile", check_compile),
        ("tests", check_tests),
        ("frontend", check_frontend),
    ]
    if args.full:
        checks.extend([
            ("evals baseline", check_evals_baseline),
            ("redteam baseline", check_redteam_baseline),
        ])

    failed = []
    for name, fn in checks:
        print(f"\n=== {name} ===")
        try:
            rc = fn()
        except Exception as e:
            print(f"❌ Excepción en {name}: {e}")
            rc = 1
        if rc != 0:
            failed.append(name)

    print("\n" + "=" * 50)
    if failed:
        print(f"❌ Fallaron: {', '.join(failed)}")
        return 1
    print("✅ Toda la verificación pasó")
    return 0


if __name__ == "__main__":
    sys.exit(main())

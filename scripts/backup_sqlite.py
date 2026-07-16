"""Backup y restore de las bases de datos SQLite de Aegis Desk.

Uso:
    python scripts/backup_sqlite.py backup
    python scripts/backup_sqlite.py restore backups/aegis_20260716_162500.db
"""

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
BACKUP_DIR = DATA_DIR / "backups"
DB_FILES = ["aegis.db", "checkpoints.sqlite", "hitl_queue.sqlite"]


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def backup() -> Path:
    """Crea un backup de todas las bases de datos SQLite en data/backups/."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = BACKUP_DIR / timestamp
    _ensure_dir(backup_dir)

    for name in DB_FILES:
        src = DATA_DIR / name
        if src.exists():
            # Backup seguro en caliente: copia con PRAGMA backup
            dst = backup_dir / name
            conn = sqlite3.connect(str(src))
            with sqlite3.connect(str(dst)) as bkp:
                conn.backup(bkp)
            conn.close()
            print(f"  ✅ {name} -> {dst}")
        else:
            print(f"  ⚠️  {name} no existe, omitido")

    print(f"\nBackup guardado en: {backup_dir}")
    return backup_dir


def restore(db_path: str) -> None:
    """Restaura aegis.db desde un backup. Luego restaura checkpoints e HITL si existen."""
    backup_dir = Path(db_path).resolve().parent
    files = ["aegis.db", "checkpoints.sqlite", "hitl_queue.sqlite"]

    for name in files:
        src = backup_dir / name
        dst = DATA_DIR / name
        if src.exists():
            _ensure_dir(DATA_DIR)
            shutil.copy2(src, dst)
            print(f"  ✅ Restaurado {dst}")
        else:
            print(f"  ⚠️  {name} no encontrado en {backup_dir}, omitido")

    print("\nRestore completado. Reinicia la API para usar las bases restauradas.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backup/restore SQLite de Aegis Desk")
    parser.add_argument("action", choices=["backup", "restore"], help="Acción a ejecutar")
    parser.add_argument("path", nargs="?", help="Ruta al backup para restore")
    args = parser.parse_args()

    if args.action == "backup":
        backup()
    elif args.action == "restore":
        if not args.path:
            parser.error("restore requiere la ruta al backup")
        restore(args.path)


if __name__ == "__main__":
    main()

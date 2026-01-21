#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Tuple


# -----------------------------
# UI helpers
# -----------------------------

SEP = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"


def println(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def eprintln(msg: str = "") -> None:
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def is_exit_token(s: str) -> bool:
    s = s.strip().lower()
    return s in {"salir", "q", "quit", "exit"}


def prompt_yn(question: str, default_yes: bool = False) -> bool:
    """
    Pregunta y/N o Y/n. Acepta 'salir' en cualquier momento.
    default_yes=False -> [y/N]
    default_yes=True  -> [Y/n]
    """
    suffix = "[Y/n]" if default_yes else "[y/N]"
    while True:
        ans = input(f"{question} {suffix}: ").strip()
        if is_exit_token(ans):
            raise UserAbort()
        if ans == "":
            return default_yes
        if ans.lower() in {"y", "yes", "s", "si", "sí"}:
            return True
        if ans.lower() in {"n", "no"}:
            return False
        println("[qcrear] Responde y/n, o escribe 'salir'.")


class UserAbort(Exception):
    pass


# -----------------------------
# Paths / repo detection
# -----------------------------

def repo_root() -> Path:
    # Asumimos scripts/qcrear.py, subimos 1 nivel
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    return repo_root() / "data"


def archivo_json_path() -> Path:
    return data_dir() / "archivo.json"


def state_dir() -> Path:
    return repo_root() / "state"


@dataclass(frozen=True)
class Preflight:
    repo: Path
    archivo_json: Path
    ok_repo: bool
    ok_archivo_json: bool


def run_preflight() -> Preflight:
    r = repo_root()
    aj = archivo_json_path()
    ok_repo = r.exists()
    ok_archivo_json = aj.exists()

    return Preflight(
        repo=r,
        archivo_json=aj,
        ok_repo=ok_repo,
        ok_archivo_json=ok_archivo_json,
    )


# -----------------------------
# Date helpers
# -----------------------------

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_yyyy_mm_dd(s: str) -> date:
    if not DATE_RE.match(s):
        raise ValueError("Formato inválido, usa YYYY-MM-DD.")
    y, m, d = map(int, s.split("-"))
    return date(y, m, d)


def load_archivo_json() -> dict:
    p = archivo_json_path()
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

def date_exists_in_archivo(archivo: dict, target: str) -> bool:
    """
    True si existe un objeto con {"date": target} en cualquier parte del JSON.
    Tolerante a estructura: busca recursivamente.
    """
    found = False

    def walk(obj):
        nonlocal found
        if found:
            return
        if isinstance(obj, dict):
            if obj.get("date") == target:
                found = True
                return
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for it in obj:
                walk(it)

    walk(archivo)
    return found


def get_next_date_from_archivo(archivo: dict) -> Optional[str]:
    """
    Intenta inferir NEXT_DATE:
    - Si hay entradas con 'date', tomar el máximo y +1 día.
    - Si la estructura es distinta, devolvemos None.

    Esto es scaffold: lo refinamos cuando integremos tu schema exacto.
    """
    dates: list[date] = []
    # Buscamos cualquier campo 'date' al nivel de items en listas comunes
    # (muy tolerante).
    def walk(obj):
        if isinstance(obj, dict):
            if "date" in obj and isinstance(obj["date"], str) and DATE_RE.match(obj["date"]):
                try:
                    dates.append(parse_yyyy_mm_dd(obj["date"]))
                except Exception:
                    pass
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for it in obj:
                walk(it)

    walk(archivo)

    if not dates:
        return None

    last = max(dates)
    nxt = last.toordinal() + 1
    return date.fromordinal(nxt).isoformat()
    
def txt_path_for_date(target: str) -> Path:
    y, m, _ = target.split("-")
    return data_dir() / "textos" / y / m / f"{target}.txt"


def txt_exists_for_date(target: str) -> bool:
    return txt_path_for_date(target).exists()


def choose_target_date(argv: list[str]) -> str:
    if len(argv) >= 2:
        # argv[0] es el script
        s = argv[1].strip()
        if is_exit_token(s):
            raise UserAbort()
        _ = parse_yyyy_mm_dd(s)  # valida
        return s

    # no date provided: propose NEXT_DATE from archivo.json
    archivo = load_archivo_json()
    nxt = get_next_date_from_archivo(archivo)

    if nxt is None:
        # fallback: hoy (pero NO asumimos zona horaria aquí; solo scaffold)
        today = date.today().isoformat()
        use = prompt_yn(f"[qcrear] No pude inferir NEXT_DATE. ¿Usar hoy ({today})?", default_yes=False)
        if not use:
            raise UserAbort()
        return today

    ok = prompt_yn(f"[qcrear] ¿Crear entrada para {nxt}?", default_yes=True)
    if not ok:
        raise UserAbort()
    return nxt


# -----------------------------
# Main
# -----------------------------

def main() -> int:
    try:
        println(SEP)
        println(" qcrear (scaffold)")
        println(SEP)

        pf = run_preflight()
        if not pf.ok_repo:
            eprintln("[qcrear] ERROR: No encuentro el repo root.")
            return 1

        # mostrar preflight bonito
        println(f"✅ repo: {pf.repo}")
        if pf.ok_archivo_json:
            println(f"✅ archivo.json: {pf.archivo_json}")
        else:
            eprintln(f"❌ archivo.json no existe: {pf.archivo_json}")
            return 1

        target = choose_target_date(sys.argv)

        # Si ya existe en archivo.json, qcrear no hace nada.
        archivo = load_archivo_json()
        if date_exists_in_archivo(archivo, target):
            println("")
            println(f"[qcrear] Ya existe una entrada publicada para {target}.")
            println("[qcrear] Usa qcambiar si quieres modificarla.")
            return 0

        println("")
        if txt_exists_for_date(target):
            println(f"[qcrear] Continuar preparación: {target} (txt ya existe)")
        else:
            println(f"[qcrear] Crear entrada: {target} (txt no existe)")


        println("[qcrear] Nota: este scaffold todavía NO hace pull, NO genera txt, NO toca archivo.json.")
        println("[qcrear] Siguiente: integrar pull robusto + validación de 3 escritos + keywords + publish gate.")
        return 0

    except UserAbort:
        println("[qcrear] Abortado por el usuario. No se hizo ningún cambio.")
        return 0
    except KeyboardInterrupt:
        println("\n[qcrear] Abortado (Ctrl-C). No se hizo ningún cambio.")
        return 130
    except Exception as e:
        eprintln(f"[qcrear] ERROR: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

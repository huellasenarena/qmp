#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional


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


class UserAbort(Exception):
    pass


def prompt_yn(question: str, default_yes: bool = False, prefix: str = "") -> bool:
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
        println(f"{prefix}Responde y/n, o escribe 'salir'.")


def prompt_choice(question: str, choices: list[str], default: Optional[str] = None) -> str:
    """
    choices: lista de strings permitidos (ej: ["r","e","n"])
    default: si no es None, Enter devuelve default
    """
    allowed = {c.lower() for c in choices}
    while True:
        suffix = f"[{'/'.join(choices)}]" if default is None else f"[{'/'.join(choices)}] (Enter={default})"
        ans = input(f"{question} {suffix}: ").strip()
        if is_exit_token(ans):
            raise UserAbort()
        if ans == "" and default is not None:
            return default
        ans_l = ans.lower()
        if ans_l in allowed:
            return ans_l
        println(f"Responde con una de: {', '.join(choices)} (o 'salir').")


# -----------------------------
# Paths / repo detection
# -----------------------------

def repo_root() -> Path:
    # Asumimos scripts/*.py, subimos 1 nivel
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
    # state dir: lo creamos si falta
    sd = state_dir()
    sd.mkdir(parents=True, exist_ok=True)
    return Preflight(repo=r, archivo_json=aj, ok_repo=ok_repo, ok_archivo_json=ok_archivo_json)


# -----------------------------
# Date helpers
# -----------------------------

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_yyyy_mm_dd(s: str) -> date:
    if not DATE_RE.match(s):
        raise ValueError("Formato inválido, usa YYYY-MM-DD.")
    y, m, d = map(int, s.split("-"))
    return date(y, m, d)


def load_archivo_json() -> object:
    p = archivo_json_path()
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def entries_list_from_archivo(archivo: object) -> list[dict]:
    """
    Soporta:
    - archivo.json como lista de entries
    - archivo.json como {"entries": [...]}
    """
    if isinstance(archivo, dict) and isinstance(archivo.get("entries"), list):
        entries = archivo["entries"]
    elif isinstance(archivo, list):
        entries = archivo
    else:
        raise RuntimeError("archivo.json inválido: raíz no es lista ni {'entries': [...]}")

    # normaliza: solo dicts
    return [e for e in entries if isinstance(e, dict)]


def find_entry_by_date(archivo: object, target: str) -> Optional[dict]:
    entries = entries_list_from_archivo(archivo)
    for e in entries:
        if e.get("date") == target:
            return e
    return None


# -----------------------------
# Hash / fingerprint helpers
# -----------------------------

def normalize_text_for_hash(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in s.split("\n")]
    while lines and lines[0].strip() == "":
        lines.pop(0)
    while lines and lines[-1].strip() == "":
        lines.pop()
    return "\n".join(lines)


def docs_fingerprint(poem: str, poem_citado: str, texto: str) -> str:
    payload = "\n\n---\n\n".join([
        normalize_text_for_hash(poem),
        normalize_text_for_hash(poem_citado),
        normalize_text_for_hash(texto),
    ])
    h = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{h}"


def extract_section(txt: str, header: str) -> str:
    txt = txt.replace("\r\n", "\n").replace("\r", "\n")
    lines = txt.split("\n")
    try:
        start = lines.index(header) + 1
    except ValueError:
        return ""
    out: list[str] = []
    for ln in lines[start:]:
        if ln.startswith("# "):
            break
        out.append(ln)
    return "\n".join(out)


def txt_fingerprint_from_file(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")
    poema = extract_section(raw, "# POEMA")
    citado = extract_section(raw, "# POEMA_CITADO")
    texto = extract_section(raw, "# TEXTO")
    if normalize_text_for_hash(poema) == "" or normalize_text_for_hash(citado) == "" or normalize_text_for_hash(texto) == "":
        return None
    return docs_fingerprint(poema, citado, texto)


# -----------------------------
# Subprocess helpers
# -----------------------------

def run_py_json(script_relpath: str, args: list[str]) -> dict:
    script_path = repo_root() / script_relpath
    if not script_path.exists():
        raise RuntimeError(f"No encuentro {script_relpath} en el repo.")

    cmd = [sys.executable, str(script_path), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        msg = stderr or stdout or f"Falló: {' '.join(cmd)}"
        raise RuntimeError(msg)

    out = (proc.stdout or "").strip()

    # Caso A: stdout ES JSON puro
    try:
        return json.loads(out) if out else {}
    except Exception:
        pass

    # Caso B: logs + línea final STATUS_JSON={...}
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("STATUS_JSON="):
            payload = line.split("=", 1)[1].strip()
            try:
                obj = json.loads(payload)
            except Exception as e:
                raise RuntimeError(
                    f"STATUS_JSON inválido ({script_relpath}): {e}\n\nLINE:\n{line}\n\nSTDOUT:\n{out}"
                )
            # tu run_py_json anuncia que devuelve dict
            if isinstance(obj, dict):
                return obj
            raise RuntimeError(
                f"STATUS_JSON no devolvió dict ({script_relpath}). Tipo={type(obj)}\n\nLINE:\n{line}"
            )

    # Si llegamos aquí: no era JSON y tampoco hubo STATUS_JSON=
    raise RuntimeError(f"stdout no es JSON ({script_relpath}).\n\nSTDOUT:\n{out}")



def write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


# -----------------------------
# Git helpers
# -----------------------------

def git(cmd: list[str]) -> str:
    proc = subprocess.run(["git", *cmd], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "").strip() or f"git {' '.join(cmd)} falló")
    return (proc.stdout or "").strip()


# -----------------------------
# archivo.json apply helper
# -----------------------------

def apply_pending_entry_into_archivo(date_str: str, pending_entry_path: Path, archivo_path: Path) -> None:
    pending = json.loads(pending_entry_path.read_text(encoding="utf-8"))
    if not isinstance(pending, dict) or pending.get("date") != date_str:
        raise RuntimeError("pending_entry.json inválido o fecha no coincide")

    data = json.loads(archivo_path.read_text(encoding="utf-8"))
    entries = data.get("entries") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise RuntimeError("archivo.json inválido: raíz no es lista ni {'entries': [...]}")

    entries = [e for e in entries if isinstance(e, dict) and e.get("date") != date_str]
    entries.append(pending)
    entries.sort(key=lambda e: e.get("date", ""), reverse=True)

    # mantener formato histórico (lista)
    archivo_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# -----------------------------
# Editor helper (keywords edit)
# -----------------------------

def open_in_editor(path: Path, prefix: str = "") -> None:
    """
    Abre el archivo con $EDITOR (fallback: nano, vi).
    """
    editor = os.environ.get("EDITOR", "").strip()
    if not editor:
        # preferir nano si existe; si no, vi
        editor = "nano"
        try:
            subprocess.run([editor, "--version"], capture_output=True, text=True)
        except Exception:
            editor = "vi"

    println(f"{prefix}Abriendo editor: {editor} {path}")
    proc = subprocess.run([editor, str(path)])
    if proc.returncode != 0:
        raise RuntimeError(f"Editor falló (code {proc.returncode}).")

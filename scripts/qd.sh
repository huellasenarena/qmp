#!/usr/bin/env zsh
# QMP — qd (zsh-only)

set -e
set -u
setopt pipefail

# -------------------------
# Helpers
# -------------------------
die() { print -u2 -- "[qd] ERROR: $*"; exit 1; }
warn() { print -u2 -- "[qd] WARN: $*"; }

confirm_yn() {
  # Usage:
  #   confirm_yn "Pregunta..."           # default NO  [y/N]
  #   confirm_yn "Pregunta..." "Y"       # default YES [Y/n]
  local prompt="$1"
  local default="${2:-N}"
  local ans

  if [[ "$default" == "Y" ]]; then
    print -n -u2 -- "[qd] $prompt [Y/n]: "
  else
    print -n -u2 -- "[qd] $prompt [y/N]: "
  fi

  read ans || true
  ans="${${ans:-}:l}"

  if [[ -z "$ans" ]]; then
    [[ "$default" == "Y" ]] && return 0 || return 1
  fi

  case "$ans" in
    y|yes|s|si|sí) return 0 ;;
    n|no) return 1 ;;
    *) [[ "$default" == "Y" ]] && return 0 || return 1 ;;
  esac
}

txt_path_for_date() {
  local d="$1"
  local y="${d[1,4]}"
  local m="${d[6,7]}"

  local p_new="${QMP_TEXTOS}/${y}/${m}/${d}.txt"
  local p_old="${QMP_TEXTOS}/${d}.txt"

  if [[ -f "$p_old" && ! -f "$p_new" ]]; then
    print -r -- "$p_old"
  else
    print -r -- "$p_new"
  fi
}

lint_template() {
  local tpl="$1"
  [[ -f "$tpl" ]] || die "Template no existe: $tpl"

  if ! grep -qE '^FECHA:' "$tpl"; then
    die "Template falta campo obligatorio FECHA: ($tpl)"
  fi
  if ! grep -q '{{DATE}}' "$tpl"; then
    die "Template no tiene placeholder {{DATE}} en FECHA: ($tpl)"
  fi

  local h
  for h in "# POEMA" "# POEMA_CITADO" "# TEXTO"; do
    if ! grep -qF "$h" "$tpl"; then
      die "Template falta header obligatorio: $h ($tpl)"
    fi
  done
}

lint_txt() {
  local txt="$1"
  local expected_date="$2"
  local archivo="$3"
  local exists_flag="$4"

  "$PYTHON" - "$txt" "$expected_date" "$archivo" "$exists_flag" <<'PY' | while IFS=$'\t' read -r level msg; do
import json, re, sys
from pathlib import Path

txt_path = Path(sys.argv[1])
expected_date = sys.argv[2]
archivo = Path(sys.argv[3])
published = (sys.argv[4] == "1")

text = txt_path.read_text(encoding="utf-8")
lines = text.splitlines()

def emit(level, msg):
    print(f"{level}\t{msg}")

meta = {}
for line in lines:
    if line.startswith("# "):
        break
    m = re.match(r"^([A-Z_]+):\s*(.*)$", line.strip())
    if m:
        meta[m.group(1)] = m.group(2)

required_keys = ["FECHA", "MY_POEM_TITLE", "POETA", "POEM_TITLE", "BOOK_TITLE"]
for k in required_keys:
    if k not in meta:
        emit("WARN", f"Falta campo de metadato {k}: (puede estar vacío, pero debe existir)")

if meta.get("FECHA") and meta["FECHA"].strip() != expected_date:
    emit("WARN", f"FECHA interna no coincide: FECHA={meta['FECHA']!r} vs esperado={expected_date!r}")

headers = ["# POEMA", "# POEMA_CITADO", "# TEXTO"]
for h in headers:
    if h not in text:
        emit("WARN", f"Falta header obligatorio: {h}")

def section_body(hdr):
    m = re.search(re.escape(hdr) + r"\n(.*?)(\n# [A-Z_]+|\Z)", text, flags=re.S)
    if not m:
        return ""
    return m.group(1).strip()

if published:
    bodies = {
        "POEMA": section_body("# POEMA"),
        "POEMA_CITADO": section_body("# POEMA_CITADO"),
        "TEXTO": section_body("# TEXTO"),
    }
    for k, body in bodies.items():
        if not body:
            emit("WARN", f"Entrada ya publicada pero sección {k} está vacía")
PY
    if [[ -n "$msg" && "$level" == "WARN" ]]; then
      warn "$msg"
    fi
  done
}

# -------------------------
# Repo / env
# -------------------------
[[ -n "${QMP_REPO:-}" ]] || die "QMP_REPO no está definido. ¿sourceaste qmp_shell.zsh?"
cd "$QMP_REPO" || die "No puedo entrar a QMP_REPO=$QMP_REPO"

local PYTHON="${QMP_PY:-$QMP_REPO/.venv/bin/python}"
[[ -x "$PYTHON" ]] || die "No existe Python del proyecto: $PYTHON (crea .venv en este entorno)"

local ARCHIVO="${ARCHIVO_JSON:-$QMP_DATA/archivo.json}"
local TEMPLATE="$QMP_DATA/templateTEXT.txt"
local PULL="$QMP_REPO/qmp/pull_keywords.py"
[[ -f "$ARCHIVO" ]] || die "Falta $ARCHIVO"
[[ -f "$TEMPLATE" ]] || die "Falta $TEMPLATE"
[[ -f "$PULL" ]] || die "Falta $PULL"

lint_template "$TEMPLATE"

# -------------------------
# Args (0 or 1)
# -------------------------
local DATE=""
if (( $# == 0 )); then
  DATE=""
elif (( $# == 1 )); then
  DATE="$1"
else
  die "Uso: qd [YYYY-MM-DD]  (0 o 1 argumento solamente)"
fi

# -------------------------
# Read min/max/next
# -------------------------
local MIN_DATE="" MAX_DATE="" NEXT_DATE=""
local HAS_PUBLISHED_ENTRIES=0

{
  local out
  out="$("$PYTHON" - "$ARCHIVO" <<'PY' 2>/dev/null
import json, sys
from datetime import date, timedelta

archivo = sys.argv[1]
data = json.load(open(archivo, encoding="utf-8"))
entries = data["entries"] if isinstance(data, dict) and isinstance(data.get("entries"), list) else data
if not isinstance(entries, list):
    print("", "", "")
    raise SystemExit(0)

dates = sorted({e.get("date","") for e in entries if isinstance(e, dict) and e.get("date")})
if not dates:
    print("", "", "")
    raise SystemExit(0)

min_d = dates[0]
max_d = dates[-1]
y,m,d = map(int, max_d.split("-"))
next_d = (date(y,m,d) + timedelta(days=1)).isoformat()
print(min_d, max_d, next_d)
PY
)"
  MIN_DATE="${out%% *}"
  out="${out#* }"
  MAX_DATE="${out%% *}"
  NEXT_DATE="${out#* }"
} || true

[[ -n "$MAX_DATE" ]] && HAS_PUBLISHED_ENTRIES=1

if [[ -z "$MIN_DATE" || -z "$MAX_DATE" || -z "$NEXT_DATE" ]]; then
  if [[ -z "$DATE" ]]; then
    die "archivo.json no tiene entradas. Usa: qd YYYY-MM-DD"
  fi
fi

if [[ -z "$DATE" ]]; then
  confirm_yn "¿Crear/abrir entrada para $NEXT_DATE?" "Y" || exit 0
  DATE="$NEXT_DATE"
fi

[[ "$DATE" == <->-<->-<-> ]] || die "Fecha inválida: $DATE (usa YYYY-MM-DD)"

if ! "$PYTHON" - "$DATE" >/dev/null 2>&1 <<'PY'
from datetime import date
import sys
try:
    date.fromisoformat(sys.argv[1])
except Exception:
    raise SystemExit(1)
PY
then
  die "Fecha inválida (no existe): $DATE"
fi

if [[ -n "$MIN_DATE" && "$DATE" < "$MIN_DATE" ]]; then
  confirm_yn "Fecha $DATE es anterior a la primera fecha publicada ($MIN_DATE). ¿Continuar igual?" || exit 0
fi

# -------------------------
# Determine if entry exists
# -------------------------
local EXISTS="0"
EXISTS="$("$PYTHON" - "$ARCHIVO" "$DATE" <<'PY' 2>/dev/null
import json, sys
archivo = sys.argv[1]
date_str = sys.argv[2]
data = json.load(open(archivo, encoding="utf-8"))
entries = data["entries"] if isinstance(data, dict) and isinstance(data.get("entries"), list) else data
if not isinstance(entries, list):
    print("0"); raise SystemExit(0)
print("1" if any(isinstance(e, dict) and e.get("date")==date_str for e in entries) else "0")
PY
)" || EXISTS="0"

if [[ "$EXISTS" == "0" && -n "${NEXT_DATE:-}" && "$DATE" != "$NEXT_DATE" ]]; then
  confirm_yn "Fecha no esperada (siguiente: $NEXT_DATE). ¿Continuar igual?" || exit 0
fi

# -------------------------
# Paths for this date
# -------------------------
local TXT="$(txt_path_for_date "$DATE")"
local CURRENT="${CURRENT_KW:-${QMP_STATE:-${QMP_SCRIPTS:-$QMP_REPO/scripts}}/current_keywords.txt}"
local PENDING="${PENDING_KW:-${QMP_STATE:-${QMP_SCRIPTS:-$QMP_REPO/scripts}}/pending_keywords.txt}"

mkdir -p "${TXT:h}" || die "No pude crear carpeta: ${TXT:h}"

if [[ ! -f "$TXT" ]]; then
  # opcional: podrías preguntar aquí, pero por ahora asumimos YES
  cp "$TEMPLATE" "$TXT"
fi

if grep -q '{{DATE}}' "$TXT"; then
  "$PYTHON" - "$DATE" "$TXT" >/dev/null 2>&1 <<'PY' || true
import sys, pathlib
date_str = sys.argv[1]
p = pathlib.Path(sys.argv[2])
t = p.read_text(encoding="utf-8")
t2 = t.replace("{{DATE}}", date_str)
if t2 != t:
    p.write_text(t2, encoding="utf-8")
PY
fi

lint_txt "$TXT" "$DATE" "$ARCHIVO" "$EXISTS"

# -------------------------
# Google Docs pulls (silencioso) + diffs + apply + open/print
# -------------------------
local CHANGES_DETECTED=0
local APPLY_CHANGES=0

# --- helpers to read existing txt values
get_meta() {
  local key="$1"
  "$PYTHON" - "$TXT" "$key" <<'PY' 2>/dev/null
import re, sys
from pathlib import Path
t = Path(sys.argv[1]).read_text(encoding="utf-8")
key = sys.argv[2]
m = re.search(rf"^{re.escape(key)}:\s*(.*)$", t, flags=re.M)
print((m.group(1) if m else "").strip())
PY
}

get_section() {
  local hdr="$1"  # e.g. "# POEMA"
  "$PYTHON" - "$TXT" "$hdr" <<'PY' 2>/dev/null
import re, sys
from pathlib import Path
t = Path(sys.argv[1]).read_text(encoding="utf-8")
hdr = sys.argv[2]
m = re.search(re.escape(hdr) + r"\n(.*?)(\n# [A-Z_]+|\Z)", t, flags=re.S)
print((m.group(1) if m else "").strip())
PY
}

# --- apply meta update (only if new non-empty)
apply_meta() {
  local key="$1"
  local val="$2"
  "$PYTHON" - "$TXT" "$key" "$val" <<'PY'
import re, sys
from pathlib import Path
path = Path(sys.argv[1])
key = sys.argv[2]
val = sys.argv[3].strip()
if not val:
    raise SystemExit(0)
text = path.read_text(encoding="utf-8")
if re.search(rf"^{re.escape(key)}:.*$", text, flags=re.M):
    text = re.sub(rf"^{re.escape(key)}:.*$", f"{key}: {val}", text, flags=re.M)
else:
    if re.search(r"^FECHA:.*$", text, flags=re.M):
        text = re.sub(r"^(FECHA:.*\n)", r"\1" + f"{key}: {val}\n", text, flags=re.M)
    else:
        text = f"{key}: {val}\n" + text
path.write_text(text, encoding="utf-8")
PY
}

apply_section_replace() {
  local hdr="$1"
  local body="$2"
  "$PYTHON" - "$TXT" "$hdr" "$body" <<'PY'
import re, sys
from pathlib import Path
path = Path(sys.argv[1])
hdr = sys.argv[2]
new_body = sys.argv[3].rstrip() + "\n"
text = path.read_text(encoding="utf-8")
pat = re.compile(re.escape(hdr) + r"\n(.*?)(\n# [A-Z_]+|\Z)", flags=re.S)
m = pat.search(text)
if not m:
    raise SystemExit(f"No encuentro sección {hdr}")
replacement = hdr + "\n\n" + new_body + m.group(2)
text = text[:m.start()] + replacement + text[m.end():]
path.write_text(text, encoding="utf-8")
PY
}

cmp_changed_meta() {
  "$PYTHON" - "$1" "$2" <<'PY' 2>/dev/null
import sys
a = " ".join((sys.argv[1] or "").strip().split())
b = " ".join((sys.argv[2] or "").strip().split())
print("1" if a != b else "0")
PY
}

cmp_changed_block() {
  "$PYTHON" - "$1" "$2" <<'PY' 2>/dev/null
import sys
def norm(s: str) -> str:
    lines = [ln.rstrip() for ln in (s or "").splitlines()]
    while lines and lines[0].strip()=="":
        lines.pop(0)
    while lines and lines[-1].strip()=="":
        lines.pop()
    return "\n".join(lines)
a = norm(sys.argv[1])
b = norm(sys.argv[2])
print("1" if a != b else "0")
PY
}

local -a CHANGED_KEYS
CHANGED_KEYS=()

# Storage for pulled content and diff flags
local PULLED_TITLE="" PULLED_POEM=""
local DOC_POET="" DOC_POEM_TITLE="" DOC_BOOK_TITLE="" DOC_POEM_CIT="" DOC_ANALYSIS=""
local TITLE_CHANGED=0 POEM_CHANGED=0
local CH_POETA=0 CH_PT=0 CH_BOOK=0 CH_CIT=0 CH_TXT=0

# Existing values from txt
local EXISTING_TITLE EXISTING_POEMA
local EX_POETA EX_POEM_TITLE EX_BOOK EX_CIT EX_TEXT

EXISTING_TITLE="$(get_meta "MY_POEM_TITLE")" || EXISTING_TITLE=""
EXISTING_POEMA="$(get_section "# POEMA")" || EXISTING_POEMA=""

EX_POETA="$(get_meta "POETA")" || EX_POETA=""
EX_POEM_TITLE="$(get_meta "POEM_TITLE")" || EX_POEM_TITLE=""
EX_BOOK="$(get_meta "BOOK_TITLE")" || EX_BOOK=""
EX_CIT="$(get_section "# POEMA_CITADO")" || EX_CIT=""
EX_TEXT="$(get_section "# TEXTO")" || EX_TEXT=""

# Pull POEMA (doc poemas)
local GDOCS_POEM="$QMP_REPO/scripts/gdocs_pull_poem_by_date.py"
if [[ -f "$GDOCS_POEM" ]]; then
  local POEM_RAW="" POEM_STATUS=0 POEM_JSON=""
  POEM_RAW="$("$PYTHON" "$GDOCS_POEM" --date "$DATE" 2>&1)" || POEM_STATUS=$?
  POEM_STATUS=${POEM_STATUS:-0}

  if [[ $POEM_STATUS -ne 0 ]]; then
    warn "Pull POEMA falló (status=$POEM_STATUS)."
    print -u2 -- "$POEM_RAW"
    confirm_yn "¿Continuar sin el pull del poema?" "Y" || exit 1
  else
    POEM_JSON="$(printf "%s" "$POEM_RAW" | "$PYTHON" -c 'import sys, json
raw=sys.stdin.read(); s=raw.lstrip()
data={"title":"","poem":""}
if s.startswith("{"):
  obj=json.loads(s); data["title"]=(obj.get("title") or obj.get("TITLE") or "").strip(); data["poem"]=(obj.get("poem") or obj.get("POEM") or "")
else:
  lines=raw.splitlines(); mode=None; tl=[]; pl=[]
  for ln in lines:
    if ln.strip()=="TITLE:": mode="title"; continue
    if ln.strip()=="POEM:": mode="poem"; continue
    if mode=="title": tl.append(ln)
    elif mode=="poem": pl.append(ln)
  data["title"]="\n".join(tl).strip(); data["poem"]="\n".join(pl).rstrip()+"\n" if pl else ""
print(json.dumps(data, ensure_ascii=False))' 2>/dev/null)" || POEM_JSON=""

    if [[ -z "$POEM_JSON" ]]; then
      warn "Pull POEMA: no pude parsear salida."
      print -u2 -- "$POEM_RAW"
      confirm_yn "¿Continuar sin el pull del poema?" "Y" || exit 1
    else
      PULLED_TITLE="$("$PYTHON" -c 'import sys,json; d=json.load(sys.stdin); print((d.get("title") or "").strip())' <<<"$POEM_JSON" 2>/dev/null)" || PULLED_TITLE=""
      PULLED_POEM="$("$PYTHON" -c 'import sys,json; d=json.load(sys.stdin); print(d.get("poem") or "", end="")' <<<"$POEM_JSON" 2>/dev/null)" || PULLED_POEM=""

      TITLE_CHANGED=0
      POEM_CHANGED=0
      if [[ -n "${PULLED_TITLE//[[:space:]]/}" ]]; then
        [[ "$(cmp_changed_meta "$EXISTING_TITLE" "$PULLED_TITLE")" == "1" ]] && TITLE_CHANGED=1
      fi
      [[ "$(cmp_changed_block "$EXISTING_POEMA" "$PULLED_POEM")" == "1" ]] && POEM_CHANGED=1

      if (( TITLE_CHANGED )); then CHANGED_KEYS+=("MY_POEM_TITLE"); fi
      if (( POEM_CHANGED )); then CHANGED_KEYS+=("#POEMA"); fi
    fi
  fi
fi

# Pull ESCRITOS (doc análisis)
local GDOCS_ANALYSIS="$QMP_REPO/scripts/gdocs_pull_analysis_by_date.py"
if [[ -f "$GDOCS_ANALYSIS" ]]; then
  local A_RAW="" A_STATUS=0
  A_RAW="$("$PYTHON" "$GDOCS_ANALYSIS" --date "$DATE" 2>&1)" || A_STATUS=$?
  A_STATUS=${A_STATUS:-0}

  if [[ $A_STATUS -ne 0 ]]; then
    warn "Pull ESCRITOS falló (status=$A_STATUS)."
    print -u2 -- "$A_RAW"
    confirm_yn "Pull ESCRITOS falló. ¿Continuar sin el pull de los escritos?" "Y" || exit 1
  else
    local AJ="$A_RAW"
    DOC_POET="$("$PYTHON" -c 'import sys,json; d=json.loads(sys.stdin.read()); print((d.get("poet") or "").strip())' <<<"$AJ" 2>/dev/null)" || DOC_POET=""
    DOC_POEM_TITLE="$("$PYTHON" -c 'import sys,json; d=json.loads(sys.stdin.read()); print((d.get("poem_title") or "").strip())' <<<"$AJ" 2>/dev/null)" || DOC_POEM_TITLE=""
    DOC_BOOK_TITLE="$("$PYTHON" -c 'import sys,json; d=json.loads(sys.stdin.read()); print((d.get("book_title") or "").strip())' <<<"$AJ" 2>/dev/null)" || DOC_BOOK_TITLE=""
    DOC_POEM_CIT="$("$PYTHON" -c 'import sys,json; d=json.loads(sys.stdin.read()); print((d.get("poem_citado") or ""))' <<<"$AJ" 2>/dev/null)" || DOC_POEM_CIT=""
    DOC_ANALYSIS="$("$PYTHON" -c 'import sys,json; d=json.loads(sys.stdin.read()); print((d.get("analysis") or ""))' <<<"$AJ" 2>/dev/null)" || DOC_ANALYSIS=""

    CH_POETA=0; CH_PT=0; CH_BOOK=0; CH_CIT=0; CH_TXT=0

    if [[ -n "${DOC_POET//[[:space:]]/}" ]]; then
      [[ "$(cmp_changed_meta "$EX_POETA" "$DOC_POET")" == "1" ]] && CH_POETA=1
    fi
    if [[ -n "${DOC_POEM_TITLE//[[:space:]]/}" ]]; then
      [[ "$(cmp_changed_meta "$EX_POEM_TITLE" "$DOC_POEM_TITLE")" == "1" ]] && CH_PT=1
    fi
    if [[ -n "${DOC_BOOK_TITLE//[[:space:]]/}" ]]; then
      [[ "$(cmp_changed_meta "$EX_BOOK" "$DOC_BOOK_TITLE")" == "1" ]] && CH_BOOK=1
    fi
    if [[ -n "${DOC_POEM_CIT//[[:space:]]/}" ]]; then
      [[ "$(cmp_changed_block "$EX_CIT" "$DOC_POEM_CIT")" == "1" ]] && CH_CIT=1
    fi
    if [[ -n "${DOC_ANALYSIS//[[:space:]]/}" ]]; then
      [[ "$(cmp_changed_block "$EX_TEXT" "$DOC_ANALYSIS")" == "1" ]] && CH_TXT=1
    fi

    if (( CH_POETA )); then CHANGED_KEYS+=("POETA"); fi
    if (( CH_PT )); then CHANGED_KEYS+=("POEM_TITLE"); fi
    if (( CH_BOOK )); then CHANGED_KEYS+=("BOOK_TITLE"); fi
    if (( CH_CIT )); then CHANGED_KEYS+=("#POEMA_CITADO"); fi
    if (( CH_TXT )); then CHANGED_KEYS+=("#TEXTO"); fi
  fi
fi

# Report diffs
if (( ${#CHANGED_KEYS[@]} > 0 )); then
  CHANGES_DETECTED=1
  print -u2 -- "[qd] Cambios detectados en Google Docs: ${CHANGED_KEYS[*]}"
else
  print -u2 -- "[qd] No hay cambios detectados en Google Docs."
fi

# Ask whether to apply (only if there are changes)
if (( CHANGES_DETECTED )); then
  if confirm_yn "¿Aplicar estos cambios al archivo local $TXT?" "N"; then
    APPLY_CHANGES=1
  else
    APPLY_CHANGES=0
  fi
fi

# Apply changes with confirmations per field/section (si APPLY_CHANGES=1)
if (( APPLY_CHANGES )); then
  if (( TITLE_CHANGED )); then
    print -u2 -- "[qd] Cambio en MY_POEM_TITLE:"
    print -u2 -- "  txt : ${EXISTING_TITLE:-<vacío>}"
    print -u2 -- "  docs: ${PULLED_TITLE}"
    confirm_yn "¿Actualizar MY_POEM_TITLE?" "N" && apply_meta "MY_POEM_TITLE" "$PULLED_TITLE"
  fi
  if (( POEM_CHANGED )); then
    print -u2 -- "[qd] Cambio en # POEMA."
    confirm_yn "¿Reemplazar # POEMA con lo de Google Docs?" "N" && apply_section_replace "# POEMA" "$PULLED_POEM"
  fi

  if (( CH_POETA )); then
    print -u2 -- "[qd] Cambio en POETA:"
    print -u2 -- "  txt : ${EX_POETA:-<vacío>}"
    print -u2 -- "  docs: ${DOC_POET}"
    confirm_yn "¿Actualizar POETA?" "N" && apply_meta "POETA" "$DOC_POET"
  fi
  if (( CH_PT )); then
    print -u2 -- "[qd] Cambio en POEM_TITLE:"
    print -u2 -- "  txt : ${EX_POEM_TITLE:-<vacío>}"
    print -u2 -- "  docs: ${DOC_POEM_TITLE}"
    confirm_yn "¿Actualizar POEM_TITLE?" "N" && apply_meta "POEM_TITLE" "$DOC_POEM_TITLE"
  fi
  if (( CH_BOOK )); then
    print -u2 -- "[qd] Cambio en BOOK_TITLE:"
    print -u2 -- "  txt : ${EX_BOOK:-<vacío>}"
    print -u2 -- "  docs: ${DOC_BOOK_TITLE}"
    confirm_yn "¿Actualizar BOOK_TITLE?" "N" && apply_meta "BOOK_TITLE" "$DOC_BOOK_TITLE"
  fi
  if (( CH_CIT )); then
    print -u2 -- "[qd] Cambio en # POEMA_CITADO."
    confirm_yn "¿Reemplazar # POEMA_CITADO con lo de Google Docs?" "N" && apply_section_replace "# POEMA_CITADO" "$DOC_POEM_CIT"
  fi
  if (( CH_TXT )); then
    print -u2 -- "[qd] Cambio en # TEXTO."
    confirm_yn "¿Reemplazar # TEXTO con lo de Google Docs?" "N" && apply_section_replace "# TEXTO" "$DOC_ANALYSIS"
  fi
fi

# Decide: open editor or print TXT (default: print)
if confirm_yn "¿Abrir editor (archivo.json + $TXT + keywords)?" "N"; then
  :  # continue
else
  print -u2 -- "[qd] No abro editor. Muestro $TXT:"
  print -- "------------------------------------------------------------"
  cat "$TXT"
  print -- "------------------------------------------------------------"
  exit 0
fi

# -------------------------
# Keywords snapshot (igual que antes)
# -------------------------
mkdir -p "${CURRENT:h}" || die "No pude crear carpeta de state: ${CURRENT:h}"

if [[ "$EXISTS" == "1" ]]; then
  if ! QMP_ARCHIVO_JSON="$ARCHIVO" "$PYTHON" "$PULL" "$DATE" "$CURRENT" >/dev/null 2>&1; then
    warn "No pude regenerar current_keywords.txt para $DATE (pull_keywords.py falló). Escribo []..."
    echo "[]" > "$CURRENT"
  fi
else
  echo "[]" > "$CURRENT"
fi

# -------------------------
# Open logic (decidido arriba)
# -------------------------
local OPEN_TXT=1

# -------------------------
# Open files (TXT focused)
# -------------------------
local -a CMD
if [[ -n "${EDITOR_CMD:-}" ]]; then
  CMD=(${=EDITOR_CMD})
elif [[ -n "${EDITOR:-}" ]]; then
  CMD=(${=EDITOR})
elif command -v code >/dev/null 2>&1; then
  CMD=(code)
elif command -v subl >/dev/null 2>&1; then
  CMD=(subl)
else
  die "No encuentro editor. Define EDITOR o EDITOR_CMD."
fi

if [[ "${CMD[1]}" == "code" ]]; then
  code -r "$CURRENT" "$PENDING" "$ARCHIVO" "$TXT"
  code -r -g "$TXT"
elif [[ "${CMD[1]}" == "subl" ]]; then
  subl -a "$CURRENT" "$PENDING" "$ARCHIVO" "$TXT"
else
  "${CMD[@]}" "$CURRENT" "$PENDING" "$ARCHIVO" "$TXT"
  "${CMD[@]}" "$TXT" >/dev/null 2>&1 || true
fi

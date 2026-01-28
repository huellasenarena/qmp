import json
from pathlib import Path

ARCHIVO = Path("data/archivo.json")

def main():
    data = json.loads(ARCHIVO.read_text(encoding="utf-8"))
    entradas = data if isinstance(data, list) else data.get("entradas", [])

    fechas = sorted(
        e["fecha"] for e in entradas
        if isinstance(e, dict) and "fecha" in e
    )

    print(f"archivo.json entries: {len(fechas)}")
    print("published dates:")
    for f in fechas[-10:]:
        print(" -", f)


if __name__ == "__main__":
    main()

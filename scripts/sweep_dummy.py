import json
from pathlib import Path

ARCHIVO = Path("data/archivo.json")

def main():
    data = json.loads(ARCHIVO.read_text(encoding="utf-8"))
    # ajusta esto si tu schema es distinto
    entradas = data if isinstance(data, list) else data.get("entradas", [])
    published = [e.get("fecha") for e in entradas if isinstance(e, dict) and e.get("fecha")]

    print("archivo.json entries:", len(entradas))
    print("published dates (sample):", published[-5:])

if __name__ == "__main__":
    main()

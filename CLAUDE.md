# Que Mal Poema — CLAUDE.md

Daily poetry publication platform at quemalpoema.com. Each day: one original poem by the author, one cited poem, and a prose analysis. Content is written in Google Docs and published to a static site via GitHub Actions.

---

## Project layout

```
/
├── core/                   # Python library (imported by scripts)
│   ├── gen_keywords.py     # Calls OpenAI to generate keyword tags for an entry
│   ├── make_pending_entry.py  # Builds a pending_entry.json from a .txt file
│   ├── merge_pending.py    # Merges pending_entry + pending_keywords into archivo.json
│   └── validate_entry.py   # Validates a .txt entry file
│
├── scripts/
│   ├── gdocs/              # Google Docs API helpers (service-account auth)
│   │   ├── _gdocs_auth.py
│   │   ├── gdocs_pull_poem_by_date.py
│   │   ├── gdocs_pull_analysis_by_date.py
│   │   └── gdocs_get_limit_date.py
│   ├── appsscript/         # Google Apps Script — managed with clasp
│   │   ├── atajo.js        # Web app (doPost): receives text from iOS/macOS Shortcut, writes to Google Docs
│   │   ├── QMP New Entry.js  # Menu-driven publish from "Entrada Pendiente" tab in Docs
│   │   ├── appsscript.json # Apps Script manifest
│   │   └── .clasp.json     # clasp config (script ID)
│   ├── qcrear.py           # Create a new entry (pull from Docs → .txt → archivo.json → commit)
│   ├── qcambiar.py         # Edit an existing draft before publishing
│   ├── update_entry.py     # Re-pull and update an already-published entry
│   └── qmp_publish.sh      # Low-level shell publish helper
│
├── data/
│   ├── archivo.json        # Master index: metadata for every published entry
│   └── textos/YYYY/MM/     # One YYYY-MM-DD.txt per entry (source of truth for poem text)
│
├── state/
│   ├── pending_entry.json  # Scratch file: entry being staged for merge
│   └── pending_keywords.txt  # Scratch file: keywords being staged for merge
│
├── site/                   # Static site (served from repo root via GitHub Pages)
│   ├── index.html          # Today's poem + analysis
│   ├── archivo.html        # Archive with month/author/keyword filters
│   ├── passe.html          # Single past entry view
│   ├── script.js           # All client-side logic
│   └── style.css
│
└── .github/workflows/
    ├── qcrear_publish_one.yml   # Manually publish a single new entry
    ├── qcrear_sweep.yml         # Sweep-publish a range of entries
    ├── update_entry.yml         # Re-pull and update a published entry
    ├── qcrear_dryrun_test.yml   # Dry-run smoke test
    └── sa_smoketest.yml         # Service-account connectivity test
```

---

## Data flow

1. Author writes in Google Docs (one doc for poems, one for analyses).
2. A GitHub Action runs a `scripts/` entrypoint with `--date YYYY-MM-DD`.
3. The script pulls content via `scripts/gdocs/`, writes `data/textos/YYYY/MM/YYYY-MM-DD.txt`, calls `core/` to build/merge metadata into `data/archivo.json`, then commits and pushes.
4. The static site reads `archivo.json` at runtime (fetch) for the archive, and fetches individual `.txt` files for poem text.

---

## Entry .txt format

```
FECHA: YYYY-MM-DD
MY_POEM_TITLE: ...
POETA: ...
POEM_TITLE: ...
BOOK_TITLE: ...

# POEMA
<original poem text>

# POEMA_CITADO
<cited poem text>

# TEXTO
<prose analysis — the published, AI-corrected version>

# BORRADOR
<optional: the author's own draft submitted for correction (their voice, with errors)>

# GUSTO
<the author's 1/2/3 rating of the cited poem — empty on PDF-mode days>

# CONVERSACION
<optional: a claude.ai share link (or pasted transcript)>
```

**`# GUSTO` — the rating, mandatory since 2026-09-11.** It carries the author's judgment of the **cited** poem on the same 1/2/3 scale the sibling recommender uses (1 = dislike, 2 = middling, 3 = like), and it is the one part of the final block that is *metadata*: `make_pending_entry.py` reads it into `archivo.json` as `analysis.gusto` (an int, omitted entirely when there is no rating, so the 164 older entries are untouched). The site never displays it.

- **The section is always present**, even on days with no poem to rate. On PDF-mode days it is written with nothing inside — the habit of having the section is what keeps the rating from being forgotten.
- `validate_entry.py` enforces it via `GUSTO_DESDE = "2026-09-11"`: entries dated on or after that **must** carry a `# GUSTO` header or publishing fails loudly (deliberately — a silent miss costs a day of training data). Entries before that date are exempt, so every published entry still validates. A present-but-empty section is an error **only when `# POEMA_CITADO` has text**; a non-empty value must be `1`, `2` or `3`.
- In PDF mode `qcrear.py` forgives *only* the "Sección vacía: # POEMA_CITADO" message, so an empty `# GUSTO` passes there while a missing one still blocks the publish.

**AI-transparency sections (`# BORRADOR`, `# CONVERSACION`)** are **independent and optional**: an entry may have neither (all pre-2026-08 entries), only `# CONVERSACION` (the common case — a claude.ai link), only `# BORRADOR`, or both. When present they come **after `# TEXTO`**, and if both are present the order is `# BORRADOR` then `# CONVERSACION` (last). They power the "Cómo usé la IA" disclosure on the site, whose tabs are built from whichever sections exist: published + conversation, published + draft, or all three. When neither is present, the site shows no disclosure at all.

- The final block is always written in the order `# BORRADOR`, `# GUSTO`, `# CONVERSACION`, and `validate_entry.py` rejects any other order among the sections present (order is checked before emptiness, since a leading `# CONVERSACION` swallows the rest of the file and would otherwise report a misleading "empty" error). It also rejects `# BORRADOR` / `# CONVERSACION` present but **empty**. These sections never reach `archivo.json` (metadata only) and are preserved across `validate_entry.py --mode normalize`.
- **`# CONVERSACION` is normally a link** (`https://claude.ai/share/…`). The site renders it as a "Ver la conversación con Claude →" button. If instead it holds pasted text, the site falls back to chat bubbles: a line containing **only** `[YO]`, `[TÚ]`, or `[CLAUDE]` (case/accent-insensitive) starts a turn. It is read **verbatim** end-to-end (its content may contain `#` lines), so `parseEntry` and `validate_entry.py` stop interpreting headers once inside it. Keep it last.

**How the author writes them (authoring flow).** The conversation happens in claude.ai, not Google Docs — and claude.ai share pages are Cloudflare-protected, so they **cannot** be scraped server-side. Instead, the author appends two plain-text markers **after** the analysis ("Versión final") in iA Writer:

```
## Borrador final
<my draft before Claude's grammar fixes>

## Gusto
3

## Conversación con IA
https://claude.ai/share/xxxxxxxx
```

`split_ia_markers` cuts each marker up to the next one that appears, so the **order in iA Writer no longer matters** — a `## Gusto` written after the conversation link is still captured, and the `.txt` always comes out in canonical order. `## Notas` remains unusable as a marker name: `atajo.js` routes it to a separate Docs tab and the pull never sees it.

These ride through the existing pipeline untouched (Atajo → `atajo.js` → Google Docs → pull) because `atajo.js` passes unrecognized `##` lines through as text and the analysis pull takes everything after the single `## Versión final`. Then `core/ia_sections.py::split_ia_markers` (called by `qcrear.py` and `update_entry.py`) splits the pulled analysis into clean `# TEXTO` + `# BORRADOR` + `# CONVERSACION`, which `render_txt` writes to the `.txt`. **No changes to `atajo.js`, the Google Docs schema, the pull, or the GitHub Actions YAML are needed.** Keep the published analysis under `## Versión final` (not `## Versión final (con IA)`) — a second "Versión final"-matching heading breaks the analysis pull.

---

## Poem rendering features

**Anchor indent (`|`)** — works in both the author's poem and the cited poem:
- A line containing `|` (not at the start) sets an anchor: everything left of `|` is measured in pixels; the `|` is removed from output.
- Subsequent lines starting with `|` are indented to that same pixel position.

**Right-aligned lines (`>>`)** — only in the author's poem:
- Lines starting with `>>` are wrapped in `.poem-right` and float to the right edge.

**Pixel measurement** uses a canvas context built from the rendered `<pre>` element's computed font.

---

## Key invariants

- `archivo.json` stores **metadata only** — it does not store poem text.
- `merge_pending.py` considers `content_changed=True` when entry metadata changes **or** when the entry is new. Poem text changes are detected separately in `update_entry.py` by comparing the old `.txt` file content.
- Fingerprints (`sha256:...`) are computed over normalized poem text to detect Docs edits.
- The site shows entries **up to yesterday** in the archive; today's entry appears only on the index.

---

## GitHub Actions secrets required

| Secret | Purpose |
|---|---|
| `QMP_GDOCS_SA_KEY_JSON` | Google service account key (full JSON) |
| `QMP_GDOCS_CONFIG_JSON` | gdocs.json config (doc IDs, sheet IDs, etc.) |
| `OPENAI_API_KEY` | Keyword generation via OpenAI |

The keyfile is written to `.secrets/sa.json` by a Python heredoc step (not bash `echo`) to avoid newline issues. `QMP_GDOCS_SA_KEYFILE` is passed via the `env:` block of the step that needs it, not via shell `export`.

---

## iOS/macOS Shortcut → Google Docs flow

The "publicar" Shortcut sends content written in iA Writer directly to Google Docs via the Apps Script web app:

1. Shortcut gets text (from share sheet or clipboard), does an empty check, then POSTs `{"text": "..."}` to the Apps Script `/exec` URL.
2. `atajo.js` (`doPost`) parses the text and writes poems/analyses to the appropriate tabs in the Google Doc.
3. Returns `{ok: true, publicados: N}` on success or `{ok: false, error: "..."}` on failure — the Shortcut shows a notification or alert accordingly.

**Input format** (plain text, no special app required):
- One or more `# Poema` and/or `# Análisis` blocks (in any combination)
- Each block must have `## Versión final` with content
- `## Notas` is optional; free text before `## Versión final` is the `pre` section
- Descriptors are optional: `# Poema` or `# Poema - my descriptor` both work

**To deploy Apps Script changes:** `cd scripts/appsscript && clasp push`

---

## Sibling project — A mi mestrofa (poetry taste predictor)

`~/Desktop/a-mi-mestrofa` · **separate repo, deliberately.**

A personal poetry recommender (Python, scikit-learn, Vertex AI, BigQuery) that learns the author's taste from rated poems and predicts whether they'll like a new one. QMP is its natural data source: every entry cites a poem the author read and judged.

**Do not merge the repos** (decided 2026-09-10). This repo *is* the website — GitHub Pages serves from the root — so anything merged in gets published, including that project's `data/poemas.csv` (187 full third-party poems plus the author's private ratings). They connect through data instead: QMP already publishes `data/archivo.json` and `data/textos/**/*.txt` over HTTPS, and the recommender consumes them. One-way coupling — nothing in QMP depends on the recommender, and a failure over there cannot break this site.

**The `## Gusto` rating — done 2026-09-11.** The marker rides through the pipeline untouched like the AI-transparency ones, is split out in `core/ia_sections.py`, and lands in `archivo.json` as `analysis.gusto`. Mandatory from that date on; see the rules under "Entry .txt format". Nothing was needed in `atajo.js`, the Docs schema, the pull or the workflows. The recommender's importer can now read the rating straight off the published `archivo.json`.

**The page — `site/mestrofa.html`.** The blog's visible half of the connection: today's cited poem, the three numbers (real rating vs. the author's model vs. a generic model) and a free-text box. It reads `API_BASE` — one line, currently the demo files in `data/mestrofa-demo*.json`, later the recommender's endpoint. It asks the server for `fecha_duelo` when the numbers belong to an earlier day; until that arrives the no-numbers state shows "no encontré nada".

Full design, hazards and open decisions: `~/Desktop/a-mi-mestrofa/docs/conexion-qmp.md`.

## Working branch

Active development lives on the `reorganize` branch (all structure changes from the 2025 reorganization). `main` is the production branch deployed to GitHub Pages.

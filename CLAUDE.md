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
<prose analysis>
```

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

## Working branch

Active development lives on the `reorganize` branch (all structure changes from the 2025 reorganization). `main` is the production branch deployed to GitHub Pages.

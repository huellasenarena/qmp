/***************************************************************
 * QMP New Entry.gs
 *
 * Flujo manual: pegar en "Entrada Pendiente" → menú QMP → publicar
 *
 * Formato aceptado en "Entrada Pendiente":
 *
 *   # Poema - descriptor      (o solo "# Poema")
 *   [contenido libre]
 *   ## Notas                  (opcional)
 *   [contenido libre]
 *   ## Versión final          (obligatorio)
 *   [contenido libre]
 *
 *   # Análisis - descriptor   (o solo "# Análisis")
 *   [metadatos opcionales]
 *   [texto libre opcional]
 *   ## Notas                  (opcional)
 *   [contenido libre]
 *   ## Versión final          (obligatorio)
 *   [contenido libre]
 *
 * Soporta múltiples bloques en una sola entrada.
 ***************************************************************/

const CONFIG = {
  TAB_POEMAS:          "Poemas Finales",
  TAB_NOTAS_POEMAS:    "Notas Poemas",
  TAB_ANALISIS:        "Análisis",
  TAB_NOTAS_ANALISIS:  "Notas Análisis",
  TAB_PENDIENTE:       "Entrada Pendiente",

  H1_POEMA_KEY:    "Poema",
  H1_ANALISIS_KEY: "Análisis",
  H2_NOTAS:        "Notas",
  H2_FINAL:        "Versión final",

  DATE_REGEX:      /\b(\d{2})(\d{2})(\d{2})\b/,
  SCAN_LAST_PARAS: 120,
};

const ZWSP = "\u200B";

/* -----------------------------
 * MENU
 * ----------------------------- */
function onOpen() {
  DocumentApp.getUi()
    .createMenu("QMP")
    .addItem("Publicar Entrada Pendiente", "qmpPublishPending")
    .addSeparator()
    .addItem("Nueva Entrada en blanco", "insertNuevaEntrada")
    .addToUi();
}

/* -----------------------------
 * MAIN
 * ----------------------------- */
function qmpPublishPending() {
  const doc         = DocumentApp.getActiveDocument();
  const tabsByTitle = indexTabsByTitle_(doc);

  const bodyPend        = mustGetTabByTitle_(tabsByTitle, CONFIG.TAB_PENDIENTE).asDocumentTab().getBody();
  const bodyPoemas      = mustGetTabByTitle_(tabsByTitle, CONFIG.TAB_POEMAS).asDocumentTab().getBody();
  const bodyNotasPoemas = mustGetTabByTitle_(tabsByTitle, CONFIG.TAB_NOTAS_POEMAS).asDocumentTab().getBody();
  const bodyAnalisis    = mustGetTabByTitle_(tabsByTitle, CONFIG.TAB_ANALISIS).asDocumentTab().getBody();
  const bodyNotasAnal   = mustGetTabByTitle_(tabsByTitle, CONFIG.TAB_NOTAS_ANALISIS).asDocumentTab().getBody();

  const parsed = parseEntradaPendiente_(bodyPend);
  validateParsed_(parsed);

  const previewLines = [];
  for (const p of parsed.poemas)
    previewLines.push(`• POEMA: "${p.descriptor}" (pre:${p.pre.length}, notas:${p.notes.length}, final:${p.final.length})`);
  for (const a of parsed.analisis)
    previewLines.push(`• ANÁLISIS: "${a.descriptor}" (pre:${a.pre.length}, notas:${a.notes.length}, final:${a.final.length})`);

  confirmOrThrow_("Detecté esto en 'Entrada Pendiente':\n\n" + previewLines.join("\n") + "\n\n¿Quieres PUBLICAR ahora?");

  for (const poema of parsed.poemas) {
    const nextDate = computeNextDateFromBodyFast_(bodyPoemas);
    assertNotDuplicateFast_(bodyPoemas, nextDate, poema.descriptor);
    if (poema.notes.length > 0)
      assertNotDuplicateFast_(bodyNotasPoemas, nextDate, poema.descriptor);
    appendPoemaFinal_(bodyPoemas, nextDate, poema.descriptor, poema.final);
    if (poema.notes.length > 0)
      appendNotes_(bodyNotasPoemas, nextDate, poema.descriptor, poema.notes);
  }

  for (const anal of parsed.analisis) {
    const nextDate = computeNextDateFromBodyFast_(bodyAnalisis);
    assertNotDuplicateFast_(bodyAnalisis, nextDate, anal.descriptor);
    if (anal.notes.length > 0)
      assertNotDuplicateFast_(bodyNotasAnal, nextDate, anal.descriptor);
    appendAnalisisFinal_(bodyAnalisis, nextDate, anal.descriptor, anal.pre, anal.final);
    if (anal.notes.length > 0)
      appendNotes_(bodyNotasAnal, nextDate, anal.descriptor, anal.notes);
  }

  clearBodySafely_(bodyPend);
  DocumentApp.getUi().alert("QMP: Publicado y borrado ✅");
}

/* -----------------------------
 * PARSE (desde body de Google Docs)
 * ----------------------------- */
function parseEntradaPendiente_(body) {
  const result = { poemas: [], analisis: [] };
  let current  = null;
  let mode     = "pre";

  const flush_ = () => {
    if (!current) return;
    if (current.kind === "poema")    result.poemas.push(current);
    if (current.kind === "analisis") result.analisis.push(current);
    current = null;
    mode    = "pre";
  };

  const pushLine_ = (text) => {
    if (!current) return;
    const item = { _text: true, text };
    if      (mode === "pre")   current.pre.push(item);
    else if (mode === "notes") current.notes.push(item);
    else                       current.final.push(item);
  };

  for (let i = 0; i < body.getNumChildren(); i++) {
    const el     = body.getChild(i);
    const elType = el.getType();

    if (elType !== DocumentApp.ElementType.PARAGRAPH &&
        elType !== DocumentApp.ElementType.LIST_ITEM) {
      if (current) {
        const item = { _text: false, el };
        if      (mode === "pre")   current.pre.push(item);
        else if (mode === "notes") current.notes.push(item);
        else                       current.final.push(item);
      }
      continue;
    }

    const p       = (elType === DocumentApp.ElementType.LIST_ITEM) ? el.asListItem() : el.asParagraph();
    const heading = p.getHeading();
    const fullRaw = stripInvisibles_(p.getText() || "");
    const subLines = fullRaw.split(/[\n\v]/);

    for (let si = 0; si < subLines.length; si++) {
      const raw = subLines[si].trim();

      const isDocH1 = si === 0 && heading === DocumentApp.ParagraphHeading.HEADING1;
      const isDocH2 = si === 0 && heading === DocumentApp.ParagraphHeading.HEADING2;
      const mdH1    = raw.match(/^#(?!#)\s+(.+)$/);
      const mdH2    = raw.match(/^##(?!#)\s+(.+)$/);
      const isH1    = !!mdH1 || isDocH1;
      const isH2    = !!mdH2 || isDocH2;
      const text    = (mdH1 ? mdH1[1] : (mdH2 ? mdH2[1] : raw)).trim();

      if (isH1) {
        flush_();
        const kind = detectKind_(text);
        if (kind) { current = makeBlock_(kind, text); mode = "pre"; }
        continue;
      }

      if (current && isH2) {
        const key = norm_(text);
        if (key === norm_(CONFIG.H2_NOTAS)) { mode = "notes"; continue; }
        if (key === norm_(CONFIG.H2_FINAL)) { mode = "final"; continue; }
      }

      if (current) pushLine_(raw);
    }
  }

  flush_();
  return result;
}

/* -----------------------------
 * KIND / BLOCK HELPERS
 * ----------------------------- */
function detectKind_(text) {
  const n = norm_(text);
  if (n === norm_(CONFIG.H1_POEMA_KEY)    || n.startsWith(norm_(CONFIG.H1_POEMA_KEY)    + " ")) return "poema";
  if (n === norm_(CONFIG.H1_ANALISIS_KEY) || n.startsWith(norm_(CONFIG.H1_ANALISIS_KEY) + " ")) return "analisis";
  return null;
}

function makeBlock_(kind, h1Text) {
  return { kind, descriptor: extractDescriptor_(h1Text, kind), pre: [], notes: [], final: [] };
}

function extractDescriptor_(h1Text, kind) {
  const keyword = (kind === "poema") ? CONFIG.H1_POEMA_KEY : CONFIG.H1_ANALISIS_KEY;
  let rest = h1Text.replace(new RegExp("^" + keyword, "i"), "").trim();
  return rest.replace(/^-+\s*/, "").trim();
}

function norm_(s) {
  return (s || "").trim().toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
}

/* -----------------------------
 * VALIDATION
 * ----------------------------- */
function validateParsed_(parsed) {
  if (parsed.poemas.length === 0 && parsed.analisis.length === 0)
    throw new Error("QMP: No encontré 'Poema' ni 'Análisis' en Entrada Pendiente.");
  for (const p of parsed.poemas)
    if (p.final.length === 0)
      throw new Error(`QMP: Poema "${p.descriptor}" no tiene ## Versión final.`);
  for (const a of parsed.analisis)
    if (a.final.length === 0)
      throw new Error(`QMP: Análisis "${a.descriptor}" no tiene ## Versión final.`);
}

/* -----------------------------
 * PUBLISH
 * ----------------------------- */
function appendPoemaFinal_(destBody, yyMmDd, descriptor, finalItems) {
  startEntry_(destBody, yyMmDd, descriptor);
  appendItemsFast_(destBody, finalItems);
  finishEntry_(destBody);
}

function appendAnalisisFinal_(destBody, yyMmDd, descriptor, preItems, finalItems) {
  startEntry_(destBody, yyMmDd, descriptor);
  appendItemsFast_(destBody, preItems);
  ensureExactlyOneBlankAtEnd_(destBody);
  writeH2_(destBody, CONFIG.H2_FINAL);
  appendItemsFast_(destBody, finalItems);
  finishEntry_(destBody);
}

function appendNotes_(destBody, yyMmDd, descriptor, notesItems) {
  startEntry_(destBody, yyMmDd, descriptor);
  appendItemsFast_(destBody, notesItems);
  finishEntry_(destBody);
}

function appendItemsFast_(destBody, items) {
  if (!items || items.length === 0) return;
  const lines = [];
  for (const item of items) {
    if (item._text) {
      lines.push(item.text);
    } else {
      const t = item.el.getType();
      if (t === DocumentApp.ElementType.PARAGRAPH)
        lines.push(item.el.asParagraph().getText() || "");
      else if (t === DocumentApp.ElementType.LIST_ITEM)
        lines.push(("• " + (item.el.asListItem().getText() || "")).trim());
      else
        lines.push("[contenido no-texto omitido]");
    }
  }
  while (lines.length > 0 && lines[0].trim() === "")              lines.shift();
  while (lines.length > 0 && lines[lines.length - 1].trim() === "") lines.pop();
  if (lines.length === 0) return;
  destBody.appendParagraph(lines.join("\n"));
}

/* -----------------------------
 * SPACING
 * ----------------------------- */
function startEntry_(destBody, yyMmDd, descriptor) {
  ensureAtMostOneTrailingBlankParagraph_(destBody);
  if (destBody.getNumChildren() > 0 && !endsWithBlankParagraph_(destBody))
    destBody.appendParagraph(ZWSP);
  const h1 = destBody.appendParagraph(descriptor ? `${yyMmDd} - ${descriptor}` : yyMmDd);
  h1.setHeading(DocumentApp.ParagraphHeading.HEADING1);
  ensureExactlyOneBlankAtEnd_(destBody);
}

function writeH2_(destBody, title) {
  const h2 = destBody.appendParagraph(title);
  h2.setHeading(DocumentApp.ParagraphHeading.HEADING2);
  ensureExactlyOneBlankAtEnd_(destBody);
}

function finishEntry_(destBody) {
  ensureAtMostOneTrailingBlankParagraph_(destBody);
}

function ensureExactlyOneBlankAtEnd_(body) {
  for (let k = 0; k < 3; k++) {
    if (!endsWithBlankParagraph_(body)) break;
    const last = body.getChild(body.getNumChildren() - 1);
    try { last.removeFromParent(); } catch (_) { break; }
  }
  body.appendParagraph(ZWSP);
}

function endsWithBlankParagraph_(body) {
  const n = body.getNumChildren();
  if (n === 0) return true;
  const last = body.getChild(n - 1);
  if (last.getType() !== DocumentApp.ElementType.PARAGRAPH) return false;
  const text = last.asParagraph().getText() || "";
  return text.trim() === "" || text === ZWSP;
}

function ensureAtMostOneTrailingBlankParagraph_(body) {
  let blanks = 0;
  for (let i = body.getNumChildren() - 1; i >= 0; i--) {
    const el   = body.getChild(i);
    if (el.getType() !== DocumentApp.ElementType.PARAGRAPH) break;
    const text = el.asParagraph().getText() || "";
    if (!(text.trim() === "" || text === ZWSP)) break;
    blanks++;
    if (blanks >= 2) el.removeFromParent();
  }
}

/* -----------------------------
 * CLEAR PENDING
 * ----------------------------- */
function clearBodySafely_(body) {
  for (let i = body.getNumChildren() - 1; i >= 1; i--) {
    try { body.getChild(i).removeFromParent(); } catch (_) {}
  }
  const survivor = body.getChild(0);
  if (survivor && survivor.getType() === DocumentApp.ElementType.PARAGRAPH) {
    survivor.asParagraph().setText(ZWSP);
    survivor.asParagraph().setHeading(DocumentApp.ParagraphHeading.NORMAL);
  }
}

/* -----------------------------
 * DUPLICATES
 * ----------------------------- */
function assertNotDuplicateFast_(destBody, yyMmDd, descriptor) {
  const header = descriptor ? `${yyMmDd} - ${descriptor}`.trim() : yyMmDd;
  const n      = destBody.getNumChildren();
  const start  = Math.max(0, n - CONFIG.SCAN_LAST_PARAS);
  for (let i = n - 1; i >= start; i--) {
    const el = destBody.getChild(i);
    if (el.getType() !== DocumentApp.ElementType.PARAGRAPH) continue;
    if ((el.asParagraph().getText() || "").trim() === header)
      throw new Error(`QMP: Duplicado detectado: "${header}".`);
  }
}

/* -----------------------------
 * DATES (YYMMDD)
 * ----------------------------- */
function computeNextDateFromBodyFast_(body) {
  const last = findLastYyMmDdInBodyFast_(body);
  if (!last) return formatYyMmDd_(new Date());
  const d = yyMmDdToDate_(last.yy, last.mm, last.dd);
  d.setDate(d.getDate() + 1);
  return formatYyMmDd_(d);
}

function findLastYyMmDdInBodyFast_(body) {
  const n     = body.getNumChildren();
  const start = Math.max(0, n - CONFIG.SCAN_LAST_PARAS);
  for (let i = n - 1; i >= start; i--) {
    const el = body.getChild(i);
    if (el.getType() !== DocumentApp.ElementType.PARAGRAPH) continue;
    const m = (el.asParagraph().getText() || "").match(CONFIG.DATE_REGEX);
    if (m) {
      const yy = +m[1], mm = +m[2], dd = +m[3];
      if (mm >= 1 && mm <= 12 && dd >= 1 && dd <= 31) return { yy, mm, dd };
    }
  }
  return null;
}

function yyMmDdToDate_(yy, mm, dd) {
  return new Date((yy <= 69 ? 2000 : 1900) + yy, mm - 1, dd);
}

function formatYyMmDd_(dateObj) {
  const tz = Session.getScriptTimeZone();
  return Utilities.formatDate(dateObj, tz, "yy") +
         Utilities.formatDate(dateObj, tz, "MM") +
         Utilities.formatDate(dateObj, tz, "dd");
}

/* -----------------------------
 * CONFIRM
 * ----------------------------- */
function confirmOrThrow_(message) {
  const ui  = DocumentApp.getUi();
  const res = ui.alert("QMP", message, ui.ButtonSet.YES_NO);
  if (res !== ui.Button.YES) throw new Error("QMP: Cancelado por el usuario.");
}

/* -----------------------------
 * TABS HELPERS
 * ----------------------------- */
function indexTabsByTitle_(doc) {
  const map = new Map();
  for (const tab of getAllTabs_(doc)) map.set(tab.getTitle(), tab);
  return map;
}

function getAllTabs_(doc) {
  const all = [];
  for (const tab of doc.getTabs()) addCurrentAndChildTabs_(tab, all);
  return all;
}

function addCurrentAndChildTabs_(tab, all) {
  all.push(tab);
  for (const child of tab.getChildTabs()) addCurrentAndChildTabs_(child, all);
}

function mustGetTabByTitle_(tabsByTitle, title) {
  const tab = tabsByTitle.get(title);
  if (!tab) throw new Error(`QMP: No encontré la pestaña "${title}".`);
  return tab;
}

function stripInvisibles_(s) {
  return (s || "").replace(/[\u200B\uFEFF\u2060\u00A0]/g, "");
}

/* -----------------------------
 * INSERTAR PLANTILLA
 * ----------------------------- */
function insertNuevaEntrada() {
  const doc    = DocumentApp.getActiveDocument();
  const cursor = doc.getCursor();
  if (!cursor) {
    DocumentApp.getUi().alert("Coloca el cursor en el documento primero.");
    return;
  }
  const lines = [
    "# Análisis -", "", "Poeta:", "Libro:", "Título:", "",
    "## Notas", "", "",
    "## Versión final", "", "",
    "# Poema -", "",
    "## Notas", "", "",
    "## Versión final", "", ""
  ];
  const element = cursor.getElement();
  const parent  = element.getParent();
  const index   = parent.getChildIndex(element);
  for (let i = lines.length - 1; i >= 0; i--) {
    parent.insertParagraph(index, lines[i]);
  }
}

/* -----------------------------
 * DIAGNOSTIC
 * ----------------------------- */
function qmpDiagnose() {
  const doc         = DocumentApp.getActiveDocument();
  const tabsByTitle = indexTabsByTitle_(doc);
  const body        = mustGetTabByTitle_(tabsByTitle, CONFIG.TAB_PENDIENTE).asDocumentTab().getBody();
  const out = [`=== Entrada Pendiente: ${body.getNumChildren()} elementos ===`];
  for (let i = 0; i < body.getNumChildren(); i++) {
    const el = body.getChild(i);
    const t  = el.getType();
    if (t === DocumentApp.ElementType.PARAGRAPH) {
      const p        = el.asParagraph();
      const stripped = stripInvisibles_(p.getText() || "");
      const heading  = p.getHeading();
      stripped.split(/[\n\v]/).forEach((sub, si) => {
        const s = sub.trim();
        const docH1 = si === 0 && heading === DocumentApp.ParagraphHeading.HEADING1;
        const docH2 = si === 0 && heading === DocumentApp.ParagraphHeading.HEADING2;
        out.push(`  [${i}.${si}] isH1=${!!s.match(/^#(?!#)/)||docH1} isH2=${!!s.match(/^##/)||docH2} "${s.slice(0,60)}"`);
      });
    } else {
      out.push(`[${i}] tipo=${t}`);
    }
  }
  const msg = out.join("\n");
  Logger.log(msg);
  DocumentApp.getUi().alert(msg.slice(0, 1500));
}
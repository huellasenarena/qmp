/***************************************************************
 * atajo.gs — Web App para el Atajo de macOS/iOS
 * Reutiliza CONFIG, ZWSP y todas las funciones de QMP New Entry.gs
 ***************************************************************/

const ATAJO_DOC_ID = "1s_n58zfRhYd1caq6QldCF99Kke3QEbPvLfl-57Q-1j0";

function testAcceso() {
  const doc = DocumentApp.openById(ATAJO_DOC_ID);
  Logger.log("OK: " + doc.getName());
}

/*
function doPost2(e) {
  return ContentService
    .createTextOutput(JSON.stringify({
      ok: true,
      recibido: e.postData.contents,
      tipo: e.postData.type
    }))
    .setMimeType(ContentService.MimeType.JSON);
}
*/

function doPost(e) {
  try {
    const payload = JSON.parse(e.postData.contents);
    const text    = (payload.text || "").trim();
    if (!text) throw new Error("Texto vacío.");

    const doc         = DocumentApp.openById(ATAJO_DOC_ID);
    const tabsByTitle = indexTabsByTitle_(doc);

    const bodyPoemas      = mustGetTabByTitle_(tabsByTitle, CONFIG.TAB_POEMAS).asDocumentTab().getBody();
    const bodyNotasPoemas = mustGetTabByTitle_(tabsByTitle, CONFIG.TAB_NOTAS_POEMAS).asDocumentTab().getBody();
    const bodyAnalisis    = mustGetTabByTitle_(tabsByTitle, CONFIG.TAB_ANALISIS).asDocumentTab().getBody();
    const bodyNotasAnal   = mustGetTabByTitle_(tabsByTitle, CONFIG.TAB_NOTAS_ANALISIS).asDocumentTab().getBody();

    const parsed = parseTexto_(text);
    validateParsed_(parsed);

    for (const poema of parsed.poemas) {
      const nextDate = computeNextDateFromBodyFast_(bodyPoemas);
      assertNotDuplicateFast_(bodyPoemas, nextDate, poema.descriptor);
      if (poema.notes.length > 0)
        assertNotDuplicateFast_(bodyNotasPoemas, nextDate, poema.descriptor);
      atajoAppendPoema_(bodyPoemas, nextDate, poema.descriptor, poema.final);
      if (poema.notes.length > 0)
        atajoAppendNotes_(bodyNotasPoemas, nextDate, poema.descriptor, poema.notes);
    }

    for (const anal of parsed.analisis) {
      const nextDate = computeNextDateFromBodyFast_(bodyAnalisis);
      assertNotDuplicateFast_(bodyAnalisis, nextDate, anal.descriptor);
      if (anal.notes.length > 0)
        assertNotDuplicateFast_(bodyNotasAnal, nextDate, anal.descriptor);
      atajoAppendAnalisis_(bodyAnalisis, nextDate, anal.descriptor, anal.pre, anal.final);
      if (anal.notes.length > 0)
        atajoAppendNotes_(bodyNotasAnal, nextDate, anal.descriptor, anal.notes);
    }

    const total = parsed.poemas.length + parsed.analisis.length;
    return ContentService
      .createTextOutput(JSON.stringify({ ok: true, publicados: total }))
      .setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ ok: false, error: err.message }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

function parseTexto_(text) {
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

  const pushLine_ = (line) => {
    if (!current) return;
    if      (mode === "pre")   current.pre.push(line);
    else if (mode === "notes") current.notes.push(line);
    else                       current.final.push(line);
  };

  for (const rawLine of text.split("\n")) {
    const line = rawLine.trimEnd();
    const mdH1 = line.trim().match(/^#(?!#)\s+(.+)$/);
    const mdH2 = line.trim().match(/^##(?!#)\s+(.+)$/);

    if (mdH1) {
      flush_();
      const kind = detectKind_(mdH1[1].trim());
      if (kind) { current = makeBlock_(kind, mdH1[1].trim()); mode = "pre"; }
      continue;
    }

    if (mdH2 && current) {
      const key = norm_(mdH2[1].trim());
      if (key === norm_(CONFIG.H2_NOTAS)) { mode = "notes"; continue; }
      if (key === norm_(CONFIG.H2_FINAL)) { mode = "final"; continue; }
    }

    if (current) pushLine_(line);
  }

  flush_();
  return result;
}

function atajoAppendLines_(destBody, lines) {
  if (!lines || lines.length === 0) return;
  const trimmed = [...lines];
  while (trimmed.length > 0 && trimmed[0].trim() === "")                trimmed.shift();
  while (trimmed.length > 0 && trimmed[trimmed.length - 1].trim() === "") trimmed.pop();
  if (trimmed.length === 0) return;
  destBody.appendParagraph(trimmed.join("\n"));
}

function atajoAppendPoema_(destBody, yyMmDd, descriptor, finalLines) {
  startEntry_(destBody, yyMmDd, descriptor);
  atajoAppendLines_(destBody, finalLines);
  finishEntry_(destBody);
}

function atajoAppendAnalisis_(destBody, yyMmDd, descriptor, preLines, finalLines) {
  startEntry_(destBody, yyMmDd, descriptor);
  atajoAppendLines_(destBody, preLines);
  ensureExactlyOneBlankAtEnd_(destBody);
  writeH2_(destBody, CONFIG.H2_FINAL);
  atajoAppendLines_(destBody, finalLines);
  finishEntry_(destBody);
}

function atajoAppendNotes_(destBody, yyMmDd, descriptor, notesLines) {
  startEntry_(destBody, yyMmDd, descriptor);
  atajoAppendLines_(destBody, notesLines);
  finishEntry_(destBody);
}
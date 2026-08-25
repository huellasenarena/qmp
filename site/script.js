// =========================
//  Utilidades (compartidas)
// =========================

function txtPathFromDate(dateStr) {
  const y = dateStr.slice(0, 4);
  const m = dateStr.slice(5, 7);
  return `/data/textos/${y}/${m}/${dateStr}.txt`;
}

function escapeHtml(s) {
  return (s || '')
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;');
}

function applyInlineFormatting(text) {
  return text
    // negrita: **texto**
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // cursiva: *texto*
    .replace(/\*(.+?)\*/g, '<em>$1</em>');
}


function textToParagraphs(text) {
  // Normalizar saltos de línea Windows/Mac antes de todo
  let raw = (text || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();

  let blockItalic = false;
  if (raw.startsWith('*') && raw.endsWith('*') && raw.length >= 2) {
    blockItalic = true;
    raw = raw.slice(1, -1).trim();
  }

  const paragraphs = raw
    .split(/\n\s*\n/)
    .map(p => p.trim())
    .filter(Boolean);

  return paragraphs.map((p, i) => {
    const classes = [];
    if (i === 0) classes.push('analysis-lead');
    if (blockItalic) classes.push('analysis-italic');

    const cls = classes.length ? ` class="${classes.join(' ')}"` : '';
    // Orden importante: escape → formatting → saltos de línea
    const html = applyInlineFormatting(escapeHtml(p)).replace(/\n/g, '<br>');
    return `<p${cls}>${html}</p>`;
  }).join('');
}


// Parser que SOLO reconoce encabezados de sección exactos
function parseEntry(text) {
  const allowed = new Set(['POEMA', 'ANALISIS', 'POEMA_CITADO', 'TEXTO', 'BORRADOR', 'CONVERSACION']);
  const sections = {};
  let current = null;
  // CONVERSACION es la última sección y se lee VERBATIM: su contenido puede
  // contener líneas que empiezan con '#', así que dejamos de interpretar
  // encabezados una vez dentro de ella.
  let verbatim = false;

  (text || '').split('\n').forEach(line => {
    if (!verbatim) {
      const m = line.match(/^#\s+(.+)\s*$/);
      if (m) {
        const name = m[1].trim();
        if (allowed.has(name)) {
          current = name;
          sections[current] = [];
          if (name === 'CONVERSACION') verbatim = true;
        } else if (current) {
          // contenido dentro de una sección
          sections[current].push(line.replace(/^#\s+/, ''));
        }
        return;
      }
    }
    if (current) sections[current].push(line);
  });

  return {
    poem: (sections['POEMA'] || []).join('\n').replace(/\s+$/,''),
    citedPoem: (sections['POEMA_CITADO'] || []).join('\n').trim(),
    analysisText: (sections['TEXTO'] || []).join('\n').trim(),
    // Artefactos de transparencia IA (opcionales)
    borrador: (sections['BORRADOR'] || []).join('\n').trim(),
    conversation: (sections['CONVERSACION'] || []).join('\n').trim()
  };
}

// =========================
//  Transparencia IA
// =========================
// Convierte la conversación en burbujas. Los turnos se separan con líneas
// que contienen SOLO un marcador de hablante: [YO] / [TÚ] / [CLAUDE]
// (sin distinción de mayúsculas/acentos). El texto antes del primer marcador
// se muestra como nota introductoria.
function renderConversation(text) {
  const raw = (text || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
  if (!raw) return '';

  const speakerRe = /^\s*\[\s*(yo|t[uú]|claude)\s*\]\s*$/i;
  const lines = raw.split('\n');

  const turns = [];
  let curSpeaker = null;
  let buf = [];

  const flush = () => {
    const body = buf.join('\n').trim();
    if (body) turns.push({ speaker: curSpeaker, body });
    buf = [];
  };

  for (const line of lines) {
    const m = line.match(speakerRe);
    if (m) {
      flush();
      curSpeaker = /claude/i.test(m[1]) ? 'claude' : 'yo';
    } else {
      buf.push(line);
    }
  }
  flush();

  // Sin marcadores: mostramos todo como bloque preformateado.
  if (!turns.some(t => t.speaker)) {
    return `<pre class="ia-conv-raw">${escapeHtml(raw)}</pre>`;
  }

  return turns.map(t => {
    if (!t.speaker) {
      return `<p class="ia-conv-note">${applyInlineFormatting(escapeHtml(t.body)).replace(/\n/g, '<br>')}</p>`;
    }
    const who = t.speaker === 'claude' ? 'Claude' : 'Yo';
    const body = applyInlineFormatting(escapeHtml(t.body)).replace(/\n/g, '<br>');
    return `<div class="ia-turn ia-turn-${t.speaker}">` +
           `<div class="ia-who">${who}</div>` +
           `<div class="ia-bubble">${body}</div></div>`;
  }).join('');
}

// La sección # CONVERSACION puede ser:
//  - una URL (modelo "enlace": link a la conversación pública en claude.ai), o
//  - texto con turnos [YO]/[CLAUDE] (modelo "embebido": burbujas).
function isUrl(s) {
  return /^https?:\/\/\S+$/i.test((s || '').trim());
}

function renderConversationView(content) {
  const raw = (content || '').trim();
  if (isUrl(raw)) {
    const safe = escapeHtml(raw);
    return `<div class="ia-conv-link">` +
      `<a class="ia-conv-button" href="${safe}" target="_blank" rel="noopener noreferrer">` +
      `Ver la conversación con Claude →</a></div>`;
  }
  return `<div class="ia-conv">${renderConversation(raw)}</div>`;
}

// Construye el bloque desplegable de transparencia y lo inserta después
// de .analysis-text. Devuelve sin hacer nada si no hay artefactos.
function renderTransparency(parsed) {
  const host = document.querySelector('.analysis-text');
  if (!host) return;

  // Limpia un widget previo (por si se re-renderiza)
  const prev = document.querySelector('.ia-transparencia');
  if (prev) prev.remove();

  const hasBorrador = !!(parsed.borrador && parsed.borrador.trim());
  const hasConv = !!(parsed.conversation && parsed.conversation.trim());
  if (!hasBorrador && !hasConv) return;

  // El análisis publicado ya está arriba en la página: aquí sólo van los
  // artefactos (mi borrador, si existe, y el enlace a la conversación).
  const views = [];
  if (hasBorrador) {
    views.push({
      id: 'borrador',
      label: 'Mi versión',
      html: textToParagraphs(parsed.borrador)
    });
  }
  if (hasConv) {
    views.push({
      id: 'conversacion',
      label: 'Conversación con Claude',
      html: renderConversationView(parsed.conversation)
    });
  }

  const section = document.createElement('section');
  section.className = 'ia-transparencia';

  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'ia-toggle';
  toggle.setAttribute('aria-expanded', 'false');
  toggle.textContent = '✦ Cómo usé la IA en este texto ↓';

  const panel = document.createElement('div');
  panel.className = 'ia-panel';
  panel.hidden = true;

  const intro = document.createElement('p');
  intro.className = 'ia-intro';
  intro.textContent =
    'Utilizo la inteligencia artificial como entrenador. Por debajo hay un ' +
    'enlace donde puedes ver mi conversación con la IA. Hago eso porque ' +
    'vivimos en un tiempo donde se utiliza a diario pero a menudo sin ' +
    'divulgación. Quiero que mi utilización de IA sea clara.';
  panel.appendChild(intro);

  const tabs = document.createElement('div');
  tabs.className = 'ia-tabs';
  const viewEls = {};

  views.forEach((v, i) => {
    const tab = document.createElement('button');
    tab.type = 'button';
    tab.className = 'ia-tab' + (i === 0 ? ' active' : '');
    tab.dataset.view = v.id;
    tab.textContent = v.label;
    tabs.appendChild(tab);

    const view = document.createElement('div');
    view.className = 'ia-view';
    view.dataset.view = v.id;
    view.hidden = i !== 0;
    view.innerHTML = v.html;
    viewEls[v.id] = view;

    tab.addEventListener('click', () => {
      tabs.querySelectorAll('.ia-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      Object.entries(viewEls).forEach(([id, el]) => { el.hidden = id !== v.id; });
    });
  });

  // Con una sola vista (el caso normal: sólo el enlace) las pestañas sobran.
  if (views.length > 1) panel.appendChild(tabs);
  views.forEach(v => panel.appendChild(viewEls[v.id]));

  toggle.addEventListener('click', () => {
    const open = panel.hidden;
    panel.hidden = !open;
    toggle.setAttribute('aria-expanded', String(open));
    toggle.textContent = open
      ? '✦ Cómo usé la IA en este texto ↑'
      : '✦ Cómo usé la IA en este texto ↓';
  });

  section.appendChild(toggle);
  section.appendChild(panel);
  host.insertAdjacentElement('afterend', section);
}


function renderPoemWithOptionalTitle(text) {
  if (!text) return '';

  const lines = text.split('\n');

  // Busca la primera línea no vacía
  let i = 0;
  while (i < lines.length && lines[i].trim() === '') i++;

  // Si hay una línea de texto y la siguiente línea es vacía => título
  if (i < lines.length - 1 && lines[i].trim() && lines[i + 1].trim() === '') {
    const title = lines[i].trim();
    const body = lines.slice(i + 2).join('\n').replace(/\s+$/,''); // conserva formato del poema

    return `<div class="poem-title">${escapeHtml(title)}</div><pre>${escapeHtml(body)}</pre>`;
  }

  // Sin título
  return `<pre>${escapeHtml(text.replace(/\s+$/,''))}</pre>`;
}

function getTodayISO() {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

function formatDate(dateStr) {
  const [y, m, d] = (dateStr || '').split('-');
  const months = ['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];
  return `${parseInt(d, 10)} de ${months[parseInt(m, 10) - 1]} de ${y}`;
}

// =========================
//  UI: pestañas + URL ?a=1
// =========================
function getTabIds() {
  // index.html usa nav-*
  if (document.getElementById('nav-poem') && document.getElementById('nav-analysis')) {
    return { poemTab: 'nav-poem', analysisTab: 'nav-analysis' };
  }
  // passe.html usa past-*
  return { poemTab: 'past-poem', analysisTab: 'past-analysis' };
}

function showPoem() {
  const { poemTab, analysisTab } = getTabIds();

  document.getElementById('poemHeader')?.style && (document.getElementById('poemHeader').style.display = 'block');
  document.getElementById('poem')?.style && (document.getElementById('poem').style.display = 'block');
  document.getElementById('analysisHeader')?.style && (document.getElementById('analysisHeader').style.display = 'none');
  document.getElementById('analysis')?.style && (document.getElementById('analysis').style.display = 'none');

  document.getElementById(poemTab)?.classList.add('active');
  document.getElementById(analysisTab)?.classList.remove('active');
}

function showAnalysis() {
  const { poemTab, analysisTab } = getTabIds();

  document.getElementById('poemHeader')?.style && (document.getElementById('poemHeader').style.display = 'none');
  document.getElementById('poem')?.style && (document.getElementById('poem').style.display = 'none');
  document.getElementById('analysisHeader')?.style && (document.getElementById('analysisHeader').style.display = 'block');
  document.getElementById('analysis')?.style && (document.getElementById('analysis').style.display = 'block');

  document.getElementById(analysisTab)?.classList.add('active');
  document.getElementById(poemTab)?.classList.remove('active');
}

function applyViewFromURL() {
  const params = new URLSearchParams(window.location.search);
  if (params.get('a') === '1') showAnalysis();
  else showPoem();
}

function setURLForPoem() {
  const url = new URL(window.location.href);
  url.searchParams.delete('a'); // conserva ?date=...
  history.replaceState({}, '', url);
}

function setURLForAnalysis() {
  const url = new URL(window.location.href);
  url.searchParams.set('a', '1'); // conserva ?date=...
  history.replaceState({}, '', url);
}

// =========================
//  Carga de contenido
// =========================

function setCitedMeta(chosen) {
  const a = chosen?.analysis || {};

  const wrap = document.querySelector('.analysis-cited-meta');
  const titleEl = document.querySelector('.analysis-cited-title');
  const sourceEl = document.querySelector('.analysis-cited-source');

  // Si la página no tiene ese bloque, no hacemos nada
  if (!wrap || !titleEl || !sourceEl) return;

  const title = (a.poem_title || '').trim();
  const poet  = (a.poet || '').trim();
  const book  = (a.book_title || '').trim();

  // Si no hay nada, ocultamos el bloque
  if (!title && !poet && !book) {
    wrap.style.display = 'none';
    titleEl.textContent = '';
    sourceEl.textContent = '';
    return;
  }

  wrap.style.display = 'block';

  // Línea 1: título en negrita (sin comillas)
  // Línea 1: título en negrita, y "/" = salto de línea
  if (title) {
    const parts = title.split('/').map(s => s.trim()).filter(Boolean);
    titleEl.innerHTML = `<strong>${parts.map(p => escapeHtml(p)).join('<br>')}</strong>`;
  } else {
    titleEl.innerHTML = '';
  }

  titleEl.style.display = title ? 'block' : 'none';

  // Línea 2: autor · poemario (solo lo que exista)
  const parts = [poet, book].filter(Boolean);
  sourceEl.textContent = parts.join(' · ');
  sourceEl.style.display = parts.length ? 'block' : 'none';
}

// =========================
//  Teatro: PDF embebido en el bloque "poema citado"
//  Regla: si chosen.analysis.pdf existe => render PDF; si no => poema citado normal
// =========================

function removeNextToggleButton_(anchorEl) {
  // El toggle del poema citado se inserta justo "afterend" del .analysis-poem
  const maybeBtn = anchorEl?.nextElementSibling;
  if (maybeBtn && maybeBtn.classList?.contains('toggle-poem-cited')) {
    maybeBtn.remove();
  }
}

function renderCitedPdfWithPdfJs_(containerEl, pdfPathRaw) {
  if (!containerEl) return;

  // normaliza ruta
  const pdfPath = (pdfPathRaw || "").trim();
  if (!pdfPath) return;

  // limpia el <pre>
  containerEl.innerHTML = "";
  containerEl.style.whiteSpace = "normal";

  // arma URL del viewer
  const viewerBase = "/site/pdfjs/web/viewer.html";
  const fileParam = encodeURIComponent(pdfPath);
  const viewerUrl = `${viewerBase}?file=${fileParam}`;

  const iframe = document.createElement("iframe");
  iframe.src = viewerUrl;
  iframe.style.width = "100%";
  iframe.style.height = "420px";
  iframe.style.border = "1px solid #ddd";
  iframe.style.borderRadius = "10px";
  iframe.setAttribute("loading", "lazy");

  containerEl.appendChild(iframe);
}


function measureTextPx(text, referenceEl) {
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');

  const cs = window.getComputedStyle(referenceEl);
  // font shorthand suficiente para measureText
  ctx.font = `${cs.fontStyle} ${cs.fontVariant} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;

  return ctx.measureText(text).width;
}

function renderPoemWithAnchorIndents(poemText, preEl) {
  const lines = (poemText || '').split('\n');

  // Medir con la misma fuente que el <pre>
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  const cs = window.getComputedStyle(preEl);

  ctx.font = `${cs.fontStyle} ${cs.fontVariant} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;

  let anchorPx = null;

  return lines.map((line) => {
    // 0) Líneas especiales a la derecha: ">> ..."
    // Se renderizan como un bloque flotante a la derecha (con gutter en CSS)
    // y NO participan en la lógica de anclas "|".
    const rightMatch = line.match(/^\s*>>\s*(.*)$/);
    if (rightMatch) {
      const content = (rightMatch[1] || '').trim();
      // Nota: sin <br>; el \n del join preserva el salto de línea del poema.
      return `<span class="poem-right">${escapeHtml(content)}</span>`;
    }

    // 1) NUEVO: soporte para "||" (continuación con prefijo)
    const dbl = line.indexOf('||');
    if (dbl !== -1) {
      const before = line.slice(0, dbl);        // texto que se conserva
      const after  = line.slice(dbl + 2);       // texto a alinear

      // si no hay ancla previa, lo tratamos como ancla (fallback razonable)
      if (anchorPx === null) {
        anchorPx = ctx.measureText(before).width;
        return escapeHtml(before + after);
      }

      const prefixPx = ctx.measureText(before).width;
      const pad = Math.max(anchorPx - prefixPx, 0);
      const content = after.replace(/^\s+/, '');

      return `${escapeHtml(before)}<span class="indent" style="padding-left:${pad}px">${escapeHtml(content)}</span>`;
    }

    // 2) Comportamiento actual con "|" (ancla o continuación al inicio)
    const pipePos = line.indexOf('|');
    if (pipePos === -1) return escapeHtml(line);

    const isContinuation = /^\s*\|/.test(line);
    const before = line.slice(0, pipePos);
    const after  = line.slice(pipePos + 1);

    if (!isContinuation) {
      // Línea ancla: "por |el dinero"
      anchorPx = ctx.measureText(before).width;
      return escapeHtml(before + after);
    }

    // Línea continuación: "| el cansancio" o "| Si alguna vez |logro juntarme,"
    const content = after.replace(/^\s+/, '');
    const pad = anchorPx ?? 0;

    // | interior en una continuación → redefine el ancla desde la posición indenteada
    const innerPipe = content.indexOf('|');
    if (innerPipe !== -1) {
      const innerBefore = content.slice(0, innerPipe);
      const innerAfter  = content.slice(innerPipe + 1);
      anchorPx = pad + ctx.measureText(innerBefore).width;
      return `<span class="indent" style="padding-left:${pad}px">${escapeHtml(innerBefore + innerAfter)}</span>`;
    }

    return `<span class="indent" style="padding-left:${pad}px">${escapeHtml(content)}</span>`;
  }).join('\n');
}



// =========================
//  Inline parser con estado (para POEMA_CITADO)
//  - *cursiva* puede cruzar líneas
//  - **negrita** también
//  - \* = asterisco literal
// =========================
function renderCitedInlineWithState(text, state) {
  let out = '';
  const s = text || '';
  let i = 0;

  while (i < s.length) {
    const ch = s[i];

    // escape: \* (o \\)
    if (ch === '\\') {
      const next = s[i + 1];
      if (next === '*' || next === '\\') {
        out += escapeHtml(next);
        i += 2;
        continue;
      }
      // si es "\" suelta, la mostramos literal
      out += '\\';
      i += 1;
      continue;
    }

    // ** toggle
    if (ch === '*' && s[i + 1] === '*') {
      state.strong = !state.strong;
      out += state.strong ? '<strong>' : '</strong>';
      i += 2;
      continue;
    }

    // * toggle
    if (ch === '*') {
      state.em = !state.em;
      out += state.em ? '<em>' : '</em>';
      i += 1;
      continue;
    }

    // normal char
    out += escapeHtml(ch);
    i += 1;
  }

  return out;
}

function renderCitedPoem(citedPoemText, ctx = null) {
  const raw = (citedPoemText || '').replace(/\r/g, '');
  const lines = raw.split('\n');

  const state = { em: false, strong: false };
  let anchorPx = null;

  const htmlLines = lines.map((line) => {
    // >> right-aligned
    const rightMatch = line.match(/^\s*>>\s*(.*)$/);
    if (rightMatch) {
      const content = (rightMatch[1] || '').trim();
      return `<span class="poem-right">${renderCitedInlineWithState(content, state)}</span>`;
    }

    // | anchor / continuation (requires ctx for pixel measurement)
    if (ctx) {
      const pipePos = line.indexOf('|');
      if (pipePos !== -1) {
        const isContinuation = /^\s*\|/.test(line);
        const before = line.slice(0, pipePos);
        const after  = line.slice(pipePos + 1);

        if (!isContinuation) {
          anchorPx = ctx.measureText(before).width;
          return renderCitedInlineWithState(before + after, state);
        } else {
          const content = after.replace(/^\s+/, '');
          const pad = anchorPx ?? 0;
          const innerPipe = content.indexOf('|');
          if (innerPipe !== -1) {
            const innerBefore = content.slice(0, innerPipe);
            const innerAfter  = content.slice(innerPipe + 1);
            anchorPx = pad + ctx.measureText(innerBefore).width;
            return `<span class="indent" style="padding-left:${pad}px">${renderCitedInlineWithState(innerBefore + innerAfter, state)}</span>`;
          }
          return `<span class="indent" style="padding-left:${pad}px">${renderCitedInlineWithState(content, state)}</span>`;
        }
      }
    }

    return renderCitedInlineWithState(line, state);
  });

  // por seguridad, cerramos tags si quedaron abiertos
  let tail = '';
  if (state.em) tail += '</em>';
  if (state.strong) tail += '</strong>';

  return htmlLines.join('\n') + tail;
}




function renderPoemWithTitleFromJson(poemText, titleFromJson) {
  const body = (poemText || '').replace(/^\s*\n+/, '').replace(/\s+$/, '');


  const wrapper = document.createElement('div');
  wrapper.className = 'poem';

  if (titleFromJson) {
    const t = document.createElement('div');
    t.className = 'poem-title';

    // Soporte: "/" significa nueva línea en el título
    // (pero sin permitir HTML; escapamos cada parte)
    const parts = titleFromJson.split('/').map(s => s.trim()).filter(Boolean);
    t.innerHTML = parts.map(p => escapeHtml(p)).join('<br>');

    wrapper.appendChild(t);
  }


  const pre = document.createElement('pre');
  pre.dataset.raw = body;          // guardamos el texto original (con |)
  pre.textContent = body.replaceAll('|', ''); // algo visible “temporal”
  wrapper.appendChild(pre);

  return wrapper;
}

// ================================
// Helper: toggle para poema citado largo
// ================================
function applyPoemCitedToggle(poemEl, maxVisibleLines = 10, minHiddenLines = 3) {
  if (!poemEl) return;

  // Texto original tal cual
  const originalText = poemEl.textContent || "";
  const lines = originalText.split(/\r?\n/);

  const totalLines = lines.length;
  const hiddenLines = totalLines - maxVisibleLines;

  // Si no hay suficientes líneas ocultas, no hacemos nada
  if (hiddenLines < minHiddenLines) {
    return;
  }

  // Guardamos versiones en data-attributes
  const visibleText = lines.slice(0, maxVisibleLines).join("\n");

  poemEl.dataset.fullText = originalText;
  poemEl.dataset.visibleText = visibleText;

  // Mostramos solo la parte visible
  poemEl.textContent = visibleText;

  // Creamos el botoncito
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "toggle-poem-cited";
  btn.textContent = "Mostrar poema completo ↓";

  // Click: alternar entre visible/parcial y completo
  btn.addEventListener("click", () => {
    const expanded = poemEl.classList.toggle("is-expanded");

    if (expanded) {
      poemEl.textContent = poemEl.dataset.fullText || "";
      btn.textContent = "Ocultar parte del poema ↑";
    } else {
      poemEl.textContent = poemEl.dataset.visibleText || "";
      btn.textContent = "Mostrar poema completo ↓";
    }
  });

  // Insertar el botón justo después del <pre class="analysis-poem">
  poemEl.insertAdjacentElement("afterend", btn);
}

// ================================
// Toggle para poema citado largo (usa renderCitedPoem)
// ================================
function setupCitedPoemToggle(poemEl, citedPoemText, maxVisibleLines = 10, minHiddenLines = 3) {
  if (!poemEl) return;

  // Canvas ctx for | anchor measurement (same font as the <pre>)
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  const cs = window.getComputedStyle(poemEl);
  ctx.font = `${cs.fontStyle} ${cs.fontVariant} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;

  // Texto original sin \r
  const raw = (citedPoemText || '').replace(/\r/g, '');
  const lines = raw.split('\n');

  const totalLines = lines.length;
  const hiddenLines = totalLines - maxVisibleLines;

  // Regla: solo mostrar toggle si hay al menos 3 líneas ocultas
  if (hiddenLines < minHiddenLines) {
    // Nada de toggle: mostramos el poema completo
    poemEl.innerHTML = renderCitedPoem(raw, ctx);
    return;
  }

  // Partición: primeras N líneas visibles
  const visibleText = lines.slice(0, maxVisibleLines).join('\n');

  // Renderizamos ambas versiones con renderCitedPoem para conservar formato
  const fullHtml = renderCitedPoem(raw, ctx);
  const visibleHtml = renderCitedPoem(visibleText, ctx);

  // Guardamos en data-attributes
  poemEl.dataset.fullHtml = fullHtml;
  poemEl.dataset.visibleHtml = visibleHtml;

  // Mostramos solo la parte visible
  poemEl.innerHTML = visibleHtml;

  // Creamos el botoncito
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'toggle-poem-cited';
  btn.textContent = 'Mostrar poema completo ↓';

  btn.addEventListener('click', () => {
    const expanded = poemEl.classList.toggle('is-expanded');

    if (expanded) {
      poemEl.innerHTML = poemEl.dataset.fullHtml || '';
      btn.textContent = 'Ocultar parte del poema ↑';
    } else {
      poemEl.innerHTML = poemEl.dataset.visibleHtml || '';
      btn.textContent = 'Mostrar poema completo ↓';
    }
  });

  // Insertar el botón justo después del <pre class="analysis-poem">
  poemEl.insertAdjacentElement('afterend', btn);
}


async function loadTodayEntry() {
  const index = await fetch('/data/archivo.json').then(r => r.json());

  const today = getTodayISO();
  const byDateAsc = [...index].sort((a, b) => a.date.localeCompare(b.date));

// 1) si existe hoy, perfecto
  let chosen = index.find(e => e.date === today);

// 2) si no existe hoy, agarrar la MÁS RECIENTE que sea <= hoy (nunca futura)
  if (!chosen) {
    const upToToday = byDateAsc.filter(e => e.date <= today);
    chosen = upToToday.at(-1);
  }

  const pageDate = document.getElementById('pageDate');
  if (pageDate) pageDate.textContent = formatDate(chosen.date);

  if (!chosen) {
    document.getElementById('poem').innerHTML = '<pre>No hay entradas todavía.</pre>';
    return;
  }

  const raw = await fetch(txtPathFromDate(chosen.date)).then(r => r.text());
  const parsed = parseEntry(raw);

  const myTitle = (chosen.my_poem_title || '').trim(); // del JSON
  const host = document.getElementById('poem');
  host.innerHTML = '';

  const title = (chosen.my_poem_title || '').trim();
  const poemEl = renderPoemWithTitleFromJson(parsed.poem, title);
  host.appendChild(poemEl);

// Ahora que el <pre> ya está en el DOM, medimos con la fuente real:
  const pre = poemEl.querySelector('pre');
  pre.innerHTML = `<span class="poem-lines">${renderPoemWithAnchorIndents(pre.dataset.raw, pre)}</span>`;
  if (!pre.querySelector('.poem-right')) pre.style.paddingRight = '0';


  // Poema citado: soporta >> (derecha) y * / ** (cursiva / negrita)
  const citedPre = document.querySelector('.analysis-poem');
  if (citedPre) {
    const pdfPath = chosen?.analysis?.pdf;

    if (pdfPath) {
      // Teatro: PDF embebido (la obra va arriba del análisis)
      renderCitedPdfWithPdfJs_(citedPre, pdfPath);
    } else {
      // Poema citado normal
      citedPre.classList.remove('analysis-pdf');
      citedPre.style.whiteSpace = 'pre-wrap';
      // aquí aplicamos el toggle bonito
      setupCitedPoemToggle(citedPre, parsed.citedPoem);
    }
  }

  document.querySelector('.analysis-text').innerHTML = textToParagraphs(parsed.analysisText);

  // Bloque de transparencia IA (si la entrada lo incluye)
  renderTransparency(parsed);

  // Meta del poema citado (2 líneas)
  setCitedMeta(chosen);

}


async function loadPastEntry() {
  const params = new URLSearchParams(window.location.search);
  const date = params.get('date');

  if (!date) {
    document.getElementById('poem').innerHTML = '<pre>Falta el parámetro ?date=YYYY-MM-DD</pre>';
    return;
  }

  const pageDate = document.getElementById('pageDate');
  if (pageDate) pageDate.textContent = formatDate(date);

  const index = await fetch('/data/archivo.json').then(r => r.json());
  const chosen = index.find(e => e.date === date);

  if (!chosen) {
    document.getElementById('poem').innerHTML = `<pre>No encontré la entrada para ${date}.</pre>`;
    return;
  }

  const raw = await fetch(txtPathFromDate(chosen.date)).then(r => r.text());
  const parsed = parseEntry(raw);

  const host = document.getElementById('poem');
  host.innerHTML = '';

  const title = (chosen.my_poem_title || '').trim();
  const poemEl = renderPoemWithTitleFromJson(parsed.poem, title);
  host.appendChild(poemEl);

// Ahora que el <pre> ya está en el DOM, medimos con la fuente real:
  const pre = poemEl.querySelector('pre');
  pre.innerHTML = `<span class="poem-lines">${renderPoemWithAnchorIndents(pre.dataset.raw, pre)}</span>`;
  if (!pre.querySelector('.poem-right')) pre.style.paddingRight = '0';

  // Poema citado: soporta >> (derecha) y * / ** (cursiva / negrita)
  const citedPre = document.querySelector('.analysis-poem');
  if (citedPre) {
    const pdfPath = chosen?.analysis?.pdf;

    if (pdfPath) {
      renderCitedPdfWithPdfJs_(citedPre, pdfPath);
    } else {
      citedPre.classList.remove('analysis-pdf');
      citedPre.style.whiteSpace = 'pre-wrap';
      setupCitedPoemToggle(citedPre, parsed.citedPoem);
    }

  }

  document.querySelector('.analysis-text').innerHTML = textToParagraphs(parsed.analysisText);

  // Bloque de transparencia IA (si la entrada lo incluye)
  renderTransparency(parsed);

  setCitedMeta(chosen);

}

// =========================
//  Tabs: mantener URL ?a=1 sin recargar
// =========================
function wireTabs() {
  const { poemTab, analysisTab } = getTabIds();

  const poemLink = document.getElementById(poemTab);
  const analysisLink = document.getElementById(analysisTab);

  if (poemLink) {
    poemLink.addEventListener('click', (e) => {
      // index.html: es <a href="index.html"> (recarga). Aquí lo evitamos:
      e.preventDefault();
      showPoem();
      setURLForPoem();
    });
  }

  if (analysisLink) {
    analysisLink.addEventListener('click', (e) => {
      e.preventDefault();
      showAnalysis();
      setURLForAnalysis();
    });
  }
}

// =========================
//  Boot
// =========================
document.addEventListener('DOMContentLoaded', () => {
  // 1) aplicar vista (poema vs análisis) desde la URL (?a=1)
  applyViewFromURL();

  // 2) enganchar tabs para que cambien sin recargar
  wireTabs();

  // 3) cargar contenido según la página
  const page = document.body?.dataset?.page;

  if (page === 'passe') {
    loadPastEntry().catch(err => {
      console.error(err);
      document.getElementById('poem').innerHTML = '<pre>Error cargando el texto.</pre>';
    });
  } else if (page === 'index') {
    loadTodayEntry().catch(err => {
      console.error(err);
      document.getElementById('poem').innerHTML = '<pre>Error cargando el texto.</pre>';
    });
  }
});

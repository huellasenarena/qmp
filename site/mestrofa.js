// =========================================================================
//  A mí me strofa
// =========================================================================
//  De dónde salen los datos. El servidor vive en el proyecto hermano
//  (a-mi-mestrofa) y sólo acepta llamadas desde https://www.quemalpoema.com,
//  así que en local la página carga pero estas dos llamadas fallan.
const SERVIDOR    = 'https://mestrofa-232425793411.us-central1.run.app';
const API_BASE    = SERVIDOR + '/hoy';
const API_PREDECIR = SERVIDOR + '/predecir';


// =========================================================================
//  TODOS LOS TEXTOS DE LA PÁGINA
//  Están todos aquí para que se puedan cambiar sin buscarlos por el archivo.
// =========================================================================
const TEXTOS = {
  // --- escritos por el autor ---
  titulo: 'A mí me strofa',

  intro: 'Acá estoy viendo si un modelo de IA puede adivinar con precisión ' +
         'mis gustos literarios. Entrené un modelo con una base de datos de ' +
         'unos 180 poemas que ya califiqué, y comparo su predicción con la ' +
         'de un modelo genérico, que no conoce mis gustos.',

  columnas: {
    nota:     'Nota real',
    modelo:   'Mi modelo',
    generico: 'Modelo genérico'
  },

  escala: {
    1: 'no para mí ahora',
    2: 'ehh',
    3: 'muy rico'
  },

  acierto: 'correctamundo',
  fallo:   'adivina de nuevo',

  // {aciertos} y {total} se cambian por los números
  marcador: '{aciertos} de {total} correctos',

  nada: 'no encontré nada',

  cajaIntro: 'acá puedes escribir un texto tuyo y ver si me va a gustar o no, ' +
             'y si mi evaluación es diferente de la de un modelo genérico',

  boton: 'leer mi mente',

  // --- provisionales, escritos por Claude a la espera de los del autor ---
  botonPensando: 'leyendo…',
  notaDia:       'estos números son del {fecha}',   // {fecha} = el día de los números
  errorDia:      'no pude cargar los datos de hoy',
  errorPrediccion: 'no pude leer este texto, probá de nuevo',
  errorTope:     'se acabaron las lecturas de hoy, volvé mañana',
  errorVacio:    'escribí algo primero',
  errorLargo:    'el texto es muy largo: 6000 caracteres como máximo',

  // El servidor manda una clave, no una frase, para que el texto sea de la
  // casa. Una clave que no esté en estas listas no enseña nada.

  // Campo "aviso" de POST /predecir: sobre el texto que pegó el visitante.
  avisos: {
    conocido:   'este poema ya está en mi corpus, así que no vale como prueba',
    sin_gemini: 'el modelo genérico no contestó esta vez',
    corto:      'es un texto muy corto: la predicción vale poco'
  },

  // Campo "motivo" de GET /hoy: por qué hoy no hay tres números.
  // Ojo con "pendiente": es pasajero, la predicción llega en minutos. Tiene
  // que sonar a "todavía no", no a "no hubo".
  motivos: {
    sin_entradas: 'todavía no hay ninguna entrada',
    sin_nota:     'todavía no le puse nota a este poema',
    pendiente:    'la predicción llega en unos minutos',
    ya_visto:     'el modelo ya conocía este poema, así que hoy no hay duelo',
    sin_texto:    'la entrada de hoy no trae poema en texto'
  }
};

const LIMITE = 6000;


// =========================================================================
//  Acceso a datos
// =========================================================================

// La caja de texto. El servidor tiene un tope de 50 lecturas al día y
// responde 429 al pasarlo; eso se avisa distinto que un fallo de verdad.
async function predecir(texto) {
  const r = await fetch(API_PREDECIR, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ texto })
  });
  if (r.status === 429) {
    const e = new Error('tope diario');
    e.tope = true;
    throw e;
  }
  if (!r.ok) throw new Error('http ' + r.status);
  return r.json();
}


// =========================================================================
//  Utilidades
// =========================================================================

function conNumeros(plantilla, valores) {
  return Object.keys(valores).reduce(
    (s, k) => s.split('{' + k + '}').join(valores[k]),
    plantilla
  );
}

function palabraDeNota(n) {
  return TEXTOS.escala[n] || '';
}

// Cuenta versos: las líneas en blanco no cuentan.
function contarVersos(texto) {
  return texto.split('\n').filter(l => l.trim() !== '').length;
}

// Cuántas líneas de verdad hay que enseñar para que se vean N versos.
// El corte cae donde cae, aunque parta una estrofa.
function lineasHastaElVerso(texto, versos) {
  const lineas = texto.split('\n');
  let n = 0;
  for (let i = 0; i < lineas.length; i++) {
    if (lineas[i].trim() !== '') {
      n++;
      if (n === versos) return i + 1;
    }
  }
  return lineas.length;
}

// Busca el PDF del día en el índice del propio sitio: el archivo de datos del
// otro proyecto no lo trae.
async function pdfDelDia(fecha) {
  try {
    const indice = await fetch('/data/archivo.json').then(r => r.json());
    const entrada = indice.find(e => e.date === fecha);
    return (entrada && entrada.analysis && entrada.analysis.pdf) || '';
  } catch (e) {
    console.error(e);
    return '';
  }
}

// Traduce una clave del servidor a una frase nuestra, buscándola en la lista
// que toque. Clave desconocida o ausente devuelve '' — nunca se enseña la
// clave cruda.
function frasePorClave(lista, clave) {
  if (!clave) return '';
  return lista[clave] || '';
}

function aviso(texto) {
  const el = document.getElementById('ms-aviso');
  el.textContent = texto;
  el.hidden = !texto;
}


// =========================================================================
//  El poema del día
// =========================================================================

function pintarFicha(datos) {
  const caja = document.getElementById('ms-meta');
  const titulo = (datos.titulo || '').trim();
  const poeta = (datos.poeta || '').trim();
  const libro = (datos.libro || '').trim();

  if (!titulo && !poeta && !libro) { caja.hidden = true; return; }

  const elTitulo = caja.querySelector('.analysis-cited-title');
  const elFuente = caja.querySelector('.analysis-cited-source');

  elTitulo.innerHTML = titulo ? '<strong>' + escapeHtml(titulo) + '</strong>' : '';
  elTitulo.style.display = titulo ? 'block' : 'none';

  const partes = [poeta, libro].filter(Boolean);
  elFuente.textContent = partes.join(' · ');
  elFuente.style.display = partes.length ? 'block' : 'none';

  caja.hidden = false;
}

// Devuelve true si consiguió enseñar algo (poema o PDF).
async function pintarPoema(datos) {
  const host = document.getElementById('ms-poema');
  host.innerHTML = '';

  let poema = '';
  try {
    const ruta = datos.texto_url || txtPathFromDate(datos.fecha);
    const bruto = await fetch(ruta).then(r => r.text());
    poema = parseEntry(bruto).citedPoem || '';
  } catch (e) {
    console.error(e);
  }

  // 1) Hay poema en texto: se enseña recortado.
  if (poema) {
    const pre = document.createElement('pre');
    pre.className = 'analysis-poem';
    host.appendChild(pre);   // tiene que estar puesto antes de medir la letra

    const versos = contarVersos(poema);
    const corte = versos <= 6
      ? poema.split('\n').length          // cabe entero, sin botón
      : lineasHastaElVerso(poema, 4);     // más de 6 versos: se ven 4

    setupCitedPoemToggle(pre, poema, corte, 1);
    return true;
  }

  // 2) No hay texto: si ese día era un PDF, se enseña el PDF.
  const pdf = await pdfDelDia(datos.fecha);
  if (pdf) {
    const caja = document.createElement('div');
    caja.className = 'ms-pdf';
    host.appendChild(caja);
    renderCitedPdfWithPdfJs_(caja, pdf);
    return true;
  }

  return false;
}


// =========================================================================
//  Los tres números y el marcador
// =========================================================================

// La palabra de la escala ("muy rico", "ehh") va sólo debajo de la nota real:
// las otras dos son adivinanzas y ahí la palabra sobra. El hueco se queda de
// todas formas para que las tres columnas sigan alineadas.
function columna(etiqueta, nota, veredicto, marcador, conPalabra) {
  const col = document.createElement('div');
  col.className = 'ms-col';

  const lab = document.createElement('div');
  lab.className = 'ms-col-lab';
  lab.textContent = etiqueta;

  const num = document.createElement('div');
  num.className = 'ms-col-num';
  num.textContent = nota;

  const pal = document.createElement('div');
  pal.className = 'ms-col-word';
  pal.textContent = conPalabra ? palabraDeNota(nota) : '';

  col.append(lab, num, pal);

  const ver = document.createElement('div');
  ver.className = 'ms-col-mark';
  ver.textContent = veredicto || '';
  col.appendChild(ver);

  if (marcador) {
    const mar = document.createElement('div');
    mar.className = 'ms-col-score';
    mar.textContent = marcador;
    col.appendChild(mar);
  }

  return col;
}

function pintarDuelo(datos) {
  const caja = document.getElementById('ms-duelo');
  const marcador = datos.marcador || {};
  const total = marcador.total;

  const cuenta = (lado) => {
    if (!lado || typeof lado.aciertos !== 'number' || typeof total !== 'number') return '';
    return conNumeros(TEXTOS.marcador, { aciertos: lado.aciertos, total: total });
  };

  caja.innerHTML = '';
  caja.append(
    columna(TEXTOS.columnas.nota, datos.gusto, '', '', true),
    columna(
      TEXTOS.columnas.modelo,
      datos.pred_modelo,
      datos.pred_modelo === datos.gusto ? TEXTOS.acierto : TEXTOS.fallo,
      cuenta(marcador.modelo),
      false
    ),
    columna(
      TEXTOS.columnas.generico,
      datos.pred_gemini,
      datos.pred_gemini === datos.gusto ? TEXTOS.acierto : TEXTOS.fallo,
      cuenta(marcador.gemini),
      false
    )
  );
  caja.hidden = false;
}

// Cuando no hay números del día, el marcador acumulado va suelto: sigue siendo
// una cuenta de muchos días, no de hoy.
function pintarMarcadorSuelto(datos) {
  const el = document.getElementById('ms-marcador-solo');
  const marcador = datos.marcador || {};
  const total = marcador.total;
  if (typeof total !== 'number') { el.hidden = true; return; }

  const trozo = (etiqueta, lado) => {
    if (!lado || typeof lado.aciertos !== 'number') return '';
    return etiqueta + ', ' + conNumeros(TEXTOS.marcador, { aciertos: lado.aciertos, total: total });
  };

  const partes = [
    trozo(TEXTOS.columnas.modelo, marcador.modelo),
    trozo(TEXTOS.columnas.generico, marcador.gemini)
  ].filter(Boolean);

  el.textContent = partes.join(' · ');
  el.hidden = partes.length === 0;
}


// =========================================================================
//  Carga del día
// =========================================================================

function hayNumeros(datos) {
  return datos.hay_duelo === true
    && typeof datos.gusto === 'number'
    && typeof datos.pred_modelo === 'number'
    && typeof datos.pred_gemini === 'number';
}

async function cargarElDia() {
  let datos;
  try {
    const r = await fetch(API_BASE);
    if (!r.ok) throw new Error('http ' + r.status);
    datos = await r.json();
  } catch (e) {
    console.error(e);
    aviso(TEXTOS.errorDia);
    return;
  }

  const elFecha = document.getElementById('ms-fecha');
  if (datos.fecha) elFecha.textContent = formatDate(datos.fecha);

  pintarFicha(datos);
  await pintarPoema(datos);

  if (hayNumeros(datos)) {
    pintarDuelo(datos);

    // Si los números son de otro día, hay que decirlo. El otro proyecto tiene
    // que mandar esa fecha en "fecha_duelo"; hoy no la manda y esto no se ve.
    if (datos.fecha_duelo && datos.fecha_duelo !== datos.fecha) {
      const nota = document.getElementById('ms-nota-dia');
      nota.textContent = conNumeros(TEXTOS.notaDia, { fecha: formatDate(datos.fecha_duelo) });
      nota.hidden = false;
    }
  } else {
    // Nunca se inventa un número que venga vacío. El servidor dice por qué
    // con una clave; si no la reconocemos, queda el aviso de siempre.
    aviso(frasePorClave(TEXTOS.motivos, datos.motivo) || TEXTOS.nada);
    pintarMarcadorSuelto(datos);
  }
}


// =========================================================================
//  La caja de texto
// =========================================================================

function barraDeConfianza(probs) {
  if (!Array.isArray(probs) || probs.length !== 3) return null;
  const suma = probs.reduce((a, b) => a + (Number(b) || 0), 0);
  if (!(suma > 0)) return null;

  const mayor = Math.max.apply(null, probs);
  const barra = document.createElement('div');
  barra.className = 'ms-probs';

  probs.forEach(p => {
    const trozo = document.createElement('span');
    trozo.className = 'ms-prob' + (p === mayor ? ' es-alta' : '');
    trozo.style.flexGrow = String((Number(p) || 0) / suma);
    barra.appendChild(trozo);
  });

  return barra;
}

function ladoPredicho(etiqueta, nota, probs) {
  const caja = document.createElement('div');
  caja.className = 'ms-pred-uno';

  const lab = document.createElement('div');
  lab.className = 'ms-col-lab';
  lab.textContent = etiqueta;

  const num = document.createElement('div');
  num.className = 'ms-pred-num';
  num.textContent = nota;

  const pal = document.createElement('div');
  pal.className = 'ms-col-word';
  pal.textContent = palabraDeNota(nota);

  caja.append(lab, num, pal);

  const barra = barraDeConfianza(probs);
  if (barra) caja.appendChild(barra);

  return caja;
}

function pintarPrediccion(res) {
  const caja = document.getElementById('ms-pred');
  caja.innerHTML = '';

  const fila = document.createElement('div');
  fila.className = 'ms-pred-fila';
  fila.append(
    ladoPredicho(TEXTOS.columnas.modelo, res.modelo, res.probs),
    ladoPredicho(TEXTOS.columnas.generico, res.gemini, null)
  );
  caja.appendChild(fila);

  // El servidor manda una clave ("corto", "conocido"…), no una frase.
  const frase = frasePorClave(TEXTOS.avisos, res.aviso);
  if (frase) {
    const nota = document.createElement('p');
    nota.className = 'ms-pred-aviso';
    nota.textContent = frase;
    caja.appendChild(nota);
  }

  caja.hidden = false;
}

function error(texto) {
  const el = document.getElementById('ms-error');
  el.textContent = texto || '';
  el.hidden = !texto;
}

function montarCaja() {
  const area = document.getElementById('ms-texto');
  const boton = document.getElementById('ms-btn');
  const contador = document.getElementById('ms-contador');
  const salida = document.getElementById('ms-pred');

  const contar = () => { contador.textContent = area.value.length + ' / ' + LIMITE; };
  area.addEventListener('input', contar);
  contar();

  boton.addEventListener('click', async () => {
    const texto = area.value;

    if (!texto.trim()) { error(TEXTOS.errorVacio); return; }
    if (texto.length > LIMITE) { error(TEXTOS.errorLargo); return; }

    error('');
    salida.hidden = true;
    boton.disabled = true;
    boton.textContent = TEXTOS.botonPensando;

    try {
      pintarPrediccion(await predecir(texto));
    } catch (e) {
      console.error(e);
      error(e && e.tope ? TEXTOS.errorTope : TEXTOS.errorPrediccion);
    } finally {
      boton.disabled = false;
      boton.textContent = TEXTOS.boton;
    }
  });
}


// =========================================================================
//  Arranque
// =========================================================================

function ponerTextosFijos() {
  document.getElementById('ms-titulo').textContent = TEXTOS.titulo;
  document.getElementById('ms-intro').textContent = TEXTOS.intro;
  document.getElementById('ms-caja-intro').textContent = TEXTOS.cajaIntro;
  document.getElementById('ms-btn').textContent = TEXTOS.boton;
}

document.addEventListener('DOMContentLoaded', () => {
  if (document.body.dataset.page !== 'mestrofa') return;
  ponerTextosFijos();
  montarCaja();
  cargarElDia();
});

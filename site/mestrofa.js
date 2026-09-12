// =========================================================================
//  A mí me strofa
// =========================================================================
//  De dónde salen los datos del día. Para pasar del ejemplo al servidor de
//  verdad no hay que cambiar nada más que esta línea.
const API_BASE = '/data/mestrofa-demo.json';  // luego: https://...run.app/hoy


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
  errorVacio:    'escribí algo primero',
  errorLargo:    'el texto es muy largo: 6000 caracteres como máximo'
};

const LIMITE = 6000;


// =========================================================================
//  Acceso a datos — lo único que cambia el día que exista el servidor
// =========================================================================

// Mientras no haya servidor: ?demo=sin-duelo enseña el segundo ejemplo.
// Esta función entera se borra cuando API_BASE apunte al servidor.
function urlDelDia() {
  const demo = new URLSearchParams(window.location.search).get('demo');
  if (demo === 'sin-duelo') return '/data/mestrofa-demo-sin-duelo.json';
  return API_BASE;
}

// La caja de texto. Hoy devuelve el ejemplo, con un retardo para que se vea
// el botón pensando. Mañana el cuerpo es un POST al servidor y nada más
// cambia en toda la página:
//   const r = await fetch(API_PREDECIR, {
//     method: 'POST',
//     headers: { 'Content-Type': 'application/json' },
//     body: JSON.stringify({ texto })
//   });
//   if (!r.ok) throw new Error('http ' + r.status);
//   return r.json();
async function predecir(texto) {
  void texto;                                    // hoy no se usa: es el ejemplo
  await new Promise(r => setTimeout(r, 700));
  const r = await fetch('/data/mestrofa-demo-predecir.json');
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
    const r = await fetch(urlDelDia());
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
    // Nunca se inventa un número que venga vacío.
    aviso(TEXTOS.nada);
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

  // El servidor puede mandar una advertencia suya sobre el texto.
  if (res.aviso) {
    const nota = document.createElement('p');
    nota.className = 'ms-pred-aviso';
    nota.textContent = res.aviso;
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
      error(TEXTOS.errorPrediccion);
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

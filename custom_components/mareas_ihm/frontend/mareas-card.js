/*
 * Tarjeta de mareas para Home Assistant (integración "mareas_ihm").
 *
 * Es un "Web Component": una etiqueta HTML nueva (<mareas-card>) que Home
 * Assistant crea cuando en un panel pones:
 *
 *   type: custom:mareas-card
 *   puerto: <id del dispositivo>   # opcional: si no, el primero
 *   vista: dia | mes               # opcional (por defecto: dia)
 *   mostrar: ambos | texto | grafico
 *   selector_puerto: true          # desplegable para cambiar de puerto
 *   titulo: "Mareas"               # opcional
 *
 * No usa librerías externas: los gráficos son SVG dibujados a mano.
 */

const DOMINIO = "mareas_ihm";
const VERSION = "1.0.0";

const TEXTOS = {
  es: {
    titulo: "Mareas", dia: "Día", mes: "Mes", hoy: "Hoy", pleamar: "Pleamar",
    bajamar: "Bajamar", ahora: "Ahora", subiendo: "subiendo", bajando: "bajando",
    sinPuertos: "No hay puertos configurados. Añade la integración «Mareas IHM».",
    sinDatos: "Sin datos para este periodo.", cargando: "Cargando…",
    sinMes: "Activa «Crear el sensor de mareas del mes» en las opciones o navega con ◀ ▶.",
    carrera: "Carrera", proxima: "Próxima",
    anterior: "Anterior", siguiente: "Siguiente",
  },
  en: {
    titulo: "Tides", dia: "Day", mes: "Month", hoy: "Today", pleamar: "High tide",
    bajamar: "Low tide", ahora: "Now", subiendo: "rising", bajando: "falling",
    sinPuertos: "No ports configured. Add the “Mareas IHM” integration.",
    sinDatos: "No data for this period.", cargando: "Loading…",
    sinMes: "Enable the monthly sensor in the options or navigate with ◀ ▶.",
    carrera: "Range", proxima: "Next",
    anterior: "Previous", siguiente: "Next",
  },
};

/* ------------------------------------------------------------------ */
/*  Utilidades                                                          */
/* ------------------------------------------------------------------ */
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

/** Suma días a una fecha 'AAAA-MM-DD' sin depender de la zona del navegador. */
function sumarDias(iso, n) {
  const [a, m, d] = iso.split("-").map(Number);
  const f = new Date(Date.UTC(a, m - 1, d + n));
  return f.toISOString().slice(0, 10);
}

/** Suma meses a {anio, mes}. */
function sumarMeses(anio, mes, n) {
  const t = anio * 12 + (mes - 1) + n;
  return { anio: Math.floor(t / 12), mes: (t % 12) + 1 };
}

const aMinutos = (hhmm) => {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
};

/** Minutos desde la medianoche en la zona horaria de Home Assistant. */
function minutoActual(tz) {
  try {
    const p = new Intl.DateTimeFormat("en-GB", { timeZone: tz, hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
      .formatToParts(new Date());
    return Number(p.find((x) => x.type === "hour").value) * 60 + Number(p.find((x) => x.type === "minute").value);
  } catch (_e) {
    const d = new Date();
    return d.getHours() * 60 + d.getMinutes();
  }
}

/** Fecha de hoy (AAAA-MM-DD) en la zona horaria de Home Assistant. */
function fechaHoy(tz) {
  try {
    return new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
  } catch (_e) {
    return new Date().toISOString().slice(0, 10);
  }
}

/** Escala "bonita" para el eje Y. */
function escalaY(min, max) {
  const rango = Math.max(max - min, 0.2);
  const paso = rango > 4 ? 1 : rango > 2 ? 0.5 : rango > 0.8 ? 0.25 : 0.1;
  let lo = Math.floor((min - rango * 0.2) / paso) * paso;
  if (min >= 0 && lo < 0) lo = 0; // no mostrar alturas negativas si no las hay
  const hi = Math.ceil((max + rango * 0.2) / paso) * paso;
  const marcas = [];
  for (let v = lo; v <= hi + 1e-9; v += paso) marcas.push(+v.toFixed(2));
  return { lo, hi, marcas };
}

/** Curva aproximada (media onda de coseno) entre extremos [{x, h}]. */
function curvaCoseno(extremos, paso) {
  const pts = [];
  for (let i = 0; i < extremos.length - 1; i++) {
    const a = extremos[i], b = extremos[i + 1];
    for (let x = a.x; x < b.x; x += paso) {
      const f = (x - a.x) / (b.x - a.x);
      pts.push([x, (a.h + b.h) / 2 + ((a.h - b.h) / 2) * Math.cos(Math.PI * f)]);
    }
  }
  if (extremos.length) pts.push([extremos.at(-1).x, extremos.at(-1).h]);
  return pts;
}

/* ------------------------------------------------------------------ */
/*  Gráfico SVG genérico                                                */
/* ------------------------------------------------------------------ */
const H = 210, M = { l: 38, r: 12, t: 18, b: 24 };

function svgGrafico({ curva, xMax, marcasX, extremos = [], banda = null, ahora = null, etiquetas = true, ancho = 600 }) {
  const W = Math.max(280, Math.round(ancho));
  const hs = curva.map((p) => p[1]).concat(extremos.map((e) => e.altura));
  const { lo, hi, marcas } = escalaY(Math.min(...hs), Math.max(...hs));
  const sx = (x) => M.l + (x / xMax) * (W - M.l - M.r);
  const sy = (h) => H - M.b - ((h - lo) / (hi - lo)) * (H - M.t - M.b);

  const linea = curva.map((p, i) => `${i ? "L" : "M"}${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join("");
  const area = `${linea}L${sx(curva.at(-1)[0]).toFixed(1)},${H - M.b}L${sx(curva[0][0]).toFixed(1)},${H - M.b}Z`;

  let s = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" class="grafico">
    <defs><linearGradient id="relleno" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="var(--mareas-agua)" stop-opacity="0.35"/>
      <stop offset="1" stop-color="var(--mareas-agua)" stop-opacity="0.02"/>
    </linearGradient></defs>`;
  if (banda) s += `<rect x="${sx(banda[0])}" y="${M.t}" width="${sx(banda[1]) - sx(banda[0])}" height="${H - M.t - M.b}" class="banda"/>`;
  for (const v of marcas) {
    s += `<line x1="${M.l}" x2="${W - M.r}" y1="${sy(v)}" y2="${sy(v)}" class="rejilla"/>
          <text x="${M.l - 6}" y="${sy(v) + 4}" class="eje" text-anchor="end">${v.toFixed(v % 1 ? (v * 10) % 1 ? 2 : 1 : 0)}</text>`;
  }
  for (const [x, txt] of marcasX) {
    s += `<line x1="${sx(x)}" x2="${sx(x)}" y1="${M.t}" y2="${H - M.b}" class="rejilla v"/>
          <text x="${sx(x)}" y="${H - 8}" class="eje" text-anchor="middle">${esc(txt)}</text>`;
  }
  s += `<path d="${area}" fill="url(#relleno)"/><path d="${linea}" class="curva${etiquetas ? "" : " fina"}"/>`;
  for (const e of extremos) {
    const x = sx(e.x), y = sy(e.altura), alta = e.tipo === "pleamar";
    s += `<circle cx="${x}" cy="${y}" r="4" class="punto ${e.tipo}"/>`;
    if (etiquetas) {
      const dy = alta ? -9 : 17;
      const anchor = x < 60 ? "start" : x > W - 60 ? "end" : "middle";
      s += `<text x="${x}" y="${y + dy}" class="etq ${e.tipo}" text-anchor="${anchor}">${esc(e.hora)} · ${e.altura.toFixed(2)} m</text>`;
    }
  }
  if (ahora) {
    s += `<line x1="${sx(ahora.x)}" x2="${sx(ahora.x)}" y1="${M.t}" y2="${H - M.b}" class="ahora"/>
          <circle cx="${sx(ahora.x)}" cy="${sy(ahora.h)}" r="5" class="ahora-punto"/>`;
  }
  s += `<line class="cursor" x1="0" x2="0" y1="${M.t}" y2="${H - M.b}" style="display:none"/>
        <circle class="cursor-punto" r="4" style="display:none"/></svg>`;
  return { svg: s, sx, sy, W };
}

/* ------------------------------------------------------------------ */
/*  La tarjeta                                                          */
/* ------------------------------------------------------------------ */
class MareasCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._vista = "dia";
    this._fecha = null; // null = hoy
    this._mes = null; // null = mes actual
    this._puerto = null;
    this._cache = new Map();
    this._firma = "";
    this._ancho = 600;
  }

  // Medimos el ancho real de la tarjeta para dibujar el SVG a escala 1:1
  // (así el texto del gráfico nunca se ve diminuto ni deformado).
  connectedCallback() {
    this._obs = new ResizeObserver(([e]) => {
      const w = Math.round(e.contentRect.width) - 32; // menos el relleno lateral
      if (w > 0 && Math.abs(w - this._ancho) > 8) {
        this._ancho = w;
        this._render();
      }
    });
    this._obs.observe(this);
  }

  disconnectedCallback() {
    this._obs?.disconnect();
  }

  static getConfigElement() {
    return document.createElement("mareas-card-editor");
  }

  static getStubConfig() {
    return { vista: "dia", mostrar: "ambos", selector_puerto: true };
  }

  setConfig(config) {
    this._config = { vista: "dia", mostrar: "ambos", selector_puerto: true, ...config };
    if (!["dia", "mes"].includes(this._config.vista)) throw new Error("vista debe ser 'dia' o 'mes'");
    if (!["ambos", "texto", "grafico"].includes(this._config.mostrar))
      throw new Error("mostrar debe ser 'ambos', 'texto' o 'grafico'");
    this._vista = this._config.vista;
    this._puerto = this._config.puerto || null;
    this._firma = "";
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    // Home Assistant llama a esto con CADA cambio de cualquier entidad.
    // Solo redibujamos si cambia algo de "nuestros" sensores.
    const p = this._puertoActual();
    const firma = p ? Object.values(p.ent).map((id) => hass.states[id]?.last_updated + (hass.states[id]?.state ?? "")).join("|") : "-";
    if (firma !== this._firma) {
      this._firma = firma;
      this._render();
    }
  }

  getCardSize() {
    return 7;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  get _t() {
    const idioma = (this._hass?.locale?.language || this._hass?.language || "es").slice(0, 2);
    return TEXTOS[idioma] || TEXTOS.en;
  }

  /** Busca los puertos (dispositivos) creados por la integración. */
  _puertos() {
    const hass = this._hass;
    if (!hass?.entities) return [];
    const porDisp = new Map();
    for (const e of Object.values(hass.entities)) {
      if (e.platform !== DOMINIO || !e.device_id || !e.translation_key) continue;
      if (!porDisp.has(e.device_id)) {
        const d = hass.devices?.[e.device_id];
        porDisp.set(e.device_id, { id: e.device_id, nombre: d?.name_by_user || d?.name || e.device_id, ent: {} });
      }
      porDisp.get(e.device_id).ent[e.translation_key] = e.entity_id;
    }
    return [...porDisp.values()].sort((a, b) => a.nombre.localeCompare(b.nombre));
  }

  _puertoActual() {
    const lista = this._puertos();
    return lista.find((p) => p.id === this._puerto) || lista[0] || null;
  }

  _estado(p, clave) {
    const id = p?.ent?.[clave];
    return id ? this._hass.states[id] : undefined;
  }

  /** Llama al servicio mareas_ihm.consultar_mareas y guarda la respuesta. */
  async _pedir(clave, datos) {
    if (this._cache.has(clave)) return;
    this._cache.set(clave, { cargando: true });
    try {
      const r = await this._hass.callWS({
        type: "call_service", domain: DOMINIO, service: "consultar_mareas",
        service_data: datos, return_response: true,
      });
      this._cache.set(clave, { datos: r.response });
    } catch (err) {
      this._cache.set(clave, { error: err?.message || String(err) });
    }
    this._render();
  }

  /* ---------- obtención de datos del periodo visible ---------- */
  _datosDia(p, hoy, tz) {
    const sensor = this._estado(p, "mareas_hoy");
    const fecha = this._fecha || sensor?.attributes?.fecha || fechaHoy(tz);
    if (sensor && sensor.attributes.fecha === fecha && sensor.attributes.curva) return { fecha, datos: sensor.attributes };
    const puertoId = sensor?.attributes?.puerto_id;
    if (!puertoId) return { fecha, error: this._t.sinDatos };
    const clave = `${puertoId}|d|${fecha}`;
    const c = this._cache.get(clave);
    if (!c) this._pedir(clave, { puerto_id: puertoId, fecha });
    return { fecha, datos: c?.datos, error: c?.error, cargando: !c || c.cargando };
  }

  _datosMes(p, hoy) {
    const sensor = this._estado(p, "mareas_mes");
    const base = { anio: +hoy.slice(0, 4), mes: +hoy.slice(5, 7) };
    const sel = this._mes || base;
    const at = sensor?.attributes;
    if (at && at.anio === sel.anio && at.mes === sel.mes && at.dias) return { sel, datos: at };
    const puertoId = this._estado(p, "mareas_hoy")?.attributes?.puerto_id || at?.puerto_id;
    if (!puertoId) return { sel, error: this._t.sinMes };
    const mesTxt = `${sel.anio}-${String(sel.mes).padStart(2, "0")}`;
    const clave = `${puertoId}|m|${mesTxt}`;
    const c = this._cache.get(clave);
    if (!c) this._pedir(clave, { puerto_id: puertoId, mes: mesTxt });
    return { sel, datos: c?.datos, error: c?.error, cargando: !c || c.cargando };
  }

  /* ---------- dibujo ---------- */
  _render() {
    if (!this._config || !this._hass) return;
    const t = this._t;
    const tz = this._hass.config?.time_zone;
    const idioma = this._hass.locale?.language || "es";
    const p = this._puertoActual();
    const lista = this._puertos();

    let cuerpo = "";
    let cabecera = "";
    if (!p) {
      cuerpo = `<div class="aviso">${esc(t.sinPuertos)}</div>`;
    } else {
      const hoy = this._estado(p, "mareas_hoy")?.attributes?.fecha || fechaHoy(tz);
      const verTexto = this._config.mostrar !== "grafico";
      const verGrafico = this._config.mostrar !== "texto";
      let etiquetaPeriodo, esActual;

      if (this._vista === "dia") {
        const r = this._datosDia(p, hoy, tz);
        const [a, m, d] = r.fecha.split("-").map(Number);
        etiquetaPeriodo = new Intl.DateTimeFormat(idioma, { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" })
          .format(new Date(Date.UTC(a, m - 1, d)));
        esActual = r.fecha === hoy;
        cuerpo = this._htmlDia(r, esActual, verTexto, verGrafico, p, tz);
      } else {
        const r = this._datosMes(p, hoy);
        etiquetaPeriodo = new Intl.DateTimeFormat(idioma, { month: "long", year: "numeric", timeZone: "UTC" })
          .format(new Date(Date.UTC(r.sel.anio, r.sel.mes - 1, 1)));
        esActual = `${r.sel.anio}-${String(r.sel.mes).padStart(2, "0")}` === hoy.slice(0, 7);
        cuerpo = this._htmlMes(r, hoy, verTexto, verGrafico);
      }

      const selector = this._config.selector_puerto && lista.length > 1
        ? `<select class="puerto" aria-label="Puerto">${lista.map((x) => `<option value="${esc(x.id)}" ${x.id === p.id ? "selected" : ""}>${esc(x.nombre)}</option>`).join("")}</select>`
        : `<span class="nombre-puerto">${esc(p.nombre)}</span>`;

      cabecera = `
        <div class="cab">
          <div class="titulo">${esc(this._config.titulo || t.titulo)} · ${selector}</div>
          <div class="pestanas" role="tablist">
            <button data-vista="dia" class="${this._vista === "dia" ? "activa" : ""}">${t.dia}</button>
            <button data-vista="mes" class="${this._vista === "mes" ? "activa" : ""}">${t.mes}</button>
          </div>
        </div>
        <div class="nav">
          <button class="icono" data-nav="-1" title="${t.anterior}">◀</button>
          <span class="periodo">${esc(etiquetaPeriodo)}</span>
          <button class="icono" data-nav="1" title="${t.siguiente}">▶</button>
          ${esActual ? "" : `<button class="hoy" data-nav="0">${t.hoy}</button>`}
        </div>`;
    }

    this.shadowRoot.innerHTML = `<style>${CSS}</style><ha-card>${cabecera}<div class="cuerpo">${cuerpo}</div></ha-card>`;
    this._conectarEventos();
  }

  _htmlDia(r, esHoy, verTexto, verGrafico, p, tz) {
    const t = this._t;
    if (r.error) return `<div class="aviso">${esc(r.error)}</div>`;
    if (!r.datos) return `<div class="aviso">${t.cargando}</div>`;
    const { mareas = [], curva = [], minutos_dia: total = 1440 } = r.datos;
    let html = "";

    if (esHoy) {
      const alt = this._estado(p, "altura_actual");
      const ten = this._estado(p, "tendencia");
      const sig = mareas.find((m) => m.minuto > minutoActual(tz));
      if (alt && !isNaN(parseFloat(alt.state))) {
        html += `<div class="ahora-txt"><span class="grande">${parseFloat(alt.state).toFixed(2)} m</span>
          <span class="${ten?.state}">${ten?.state === "subiendo" ? "▲" : ten?.state === "bajando" ? "▼" : ""} ${esc(t[ten?.state] || "")}</span>
          ${sig ? `<span class="sec">· ${t.proxima} ${sig.tipo === "pleamar" ? t.pleamar.toLowerCase() : t.bajamar.toLowerCase()} ${esc(sig.hora)}</span>` : ""}</div>`;
      }
    }

    if (verGrafico && curva.length) {
      const marcasX = [0, 180, 360, 540, 720, 900, 1080, 1260].filter((x) => x < total).map((x) => [x, `${String(x / 60).padStart(2, "0")}h`]);
      let ahora = null;
      if (esHoy) {
        const x = minutoActual(tz);
        const i = curva.findIndex((q) => q[0] >= x);
        if (i > 0) {
          const [x0, h0] = curva[i - 1], [x1, h1] = curva[i];
          ahora = { x, h: h0 + ((h1 - h0) * (x - x0)) / (x1 - x0 || 1) };
        }
      }
      const g = svgGrafico({ curva, xMax: total, marcasX, extremos: mareas.map((m) => ({ ...m, x: m.minuto })), ahora, ancho: this._ancho });
      this._hover = { curva, sx: g.sx, sy: g.sy, W: g.W, fmt: (q) => `${String(Math.floor(q[0] / 60) % 24).padStart(2, "0")}:${String(Math.round(q[0] % 60)).padStart(2, "0")} · ${q[1].toFixed(2)} m` };
      html += `<div class="caja-grafico">${g.svg}<div class="tooltip"></div></div>`;
    }

    if (verTexto) {
      if (!mareas.length) html += `<div class="aviso">${t.sinDatos}</div>`;
      html += `<ul class="lista">${mareas.map((m) => `
        <li class="${m.tipo}"><span class="flecha">${m.tipo === "pleamar" ? "▲" : "▼"}</span>
          <span class="tipo">${m.tipo === "pleamar" ? t.pleamar : t.bajamar}</span>
          <span class="hora">${esc(m.hora)}</span><span class="alt">${m.altura.toFixed(2)} m</span></li>`).join("")}</ul>`;
    }
    return html;
  }

  _htmlMes(r, hoy, verTexto, verGrafico) {
    const t = this._t;
    if (r.error) return `<div class="aviso">${esc(r.error)}</div>`;
    if (!r.datos) return `<div class="aviso">${t.cargando}</div>`;
    const dias = r.datos.dias || [];
    if (!dias.length) return `<div class="aviso">${t.sinDatos}</div>`;
    const { anio, mes } = r.sel;
    const nDias = new Date(Date.UTC(anio, mes, 0)).getUTCDate();
    const idioma = this._hass.locale?.language || "es";
    let html = "";

    if (verGrafico) {
      const extremos = dias.flatMap((d) => {
        const n = +d.fecha.slice(8, 10);
        return d.mareas.map((m) => ({ ...m, x: (n - 1) * 1440 + aMinutos(m.hora), h: m.altura }));
      });
      const curva = curvaCoseno(extremos, 30);
      const marcasX = [1, 5, 10, 15, 20, 25, 30].filter((d) => d <= nDias).map((d) => [(d - 1) * 1440 + 720, String(d)]);
      let banda = null;
      if (hoy.slice(0, 7) === `${anio}-${String(mes).padStart(2, "0")}`) {
        const n = +hoy.slice(8, 10);
        banda = [(n - 1) * 1440, n * 1440];
      }
      const g = svgGrafico({ curva, xMax: nDias * 1440, marcasX, banda, etiquetas: false, ancho: this._ancho });
      this._hover = {
        curva, sx: g.sx, sy: g.sy, W: g.W,
        fmt: (q) => {
          const d = Math.floor(q[0] / 1440) + 1, mm = q[0] % 1440;
          return `${d}/${mes} ${String(Math.floor(mm / 60)).padStart(2, "0")}:${String(mm % 60).padStart(2, "0")} · ${q[1].toFixed(2)} m`;
        },
      };
      html += `<div class="caja-grafico">${g.svg}<div class="tooltip"></div></div>`;
    }

    if (verTexto) {
      const fmtDia = new Intl.DateTimeFormat(idioma, { weekday: "short", day: "numeric", timeZone: "UTC" });
      const celdas = (d, tipo) => d.mareas.filter((m) => m.tipo === tipo)
        .map((m) => `<span>${esc(m.hora)} <small>${m.altura.toFixed(2)}</small></span>`).join("");
      html += `<div class="tabla-mes"><table>
        <thead><tr><th></th><th class="pleamar">▲ ${t.pleamar}</th><th class="bajamar">▼ ${t.bajamar}</th><th>${t.carrera}</th></tr></thead>
        <tbody>${dias.map((d) => {
          const [a, m, n] = d.fecha.split("-").map(Number);
          return `<tr data-fecha="${d.fecha}" class="${d.fecha === hoy ? "hoy" : ""}">
            <td class="d">${esc(fmtDia.format(new Date(Date.UTC(a, m - 1, n))))}</td>
            <td>${celdas(d, "pleamar")}</td><td>${celdas(d, "bajamar")}</td>
            <td class="c">${d.carrera != null ? d.carrera.toFixed(2) : "–"}</td></tr>`;
        }).join("")}</tbody></table></div>`;
    }
    return html;
  }

  _conectarEventos() {
    const raiz = this.shadowRoot;
    raiz.querySelectorAll("[data-vista]").forEach((b) =>
      b.addEventListener("click", () => { this._vista = b.dataset.vista; this._render(); }));
    raiz.querySelector("select.puerto")?.addEventListener("change", (e) => {
      this._puerto = e.target.value; this._firma = ""; this.hass = this._hass;
    });
    // Tabla del mes: la primera vez se desplaza hasta hoy; después se respeta
    // donde la dejó el usuario (aunque la tarjeta se redibuje).
    const tabla = raiz.querySelector(".tabla-mes");
    if (tabla) {
      const claveMes = `${this._puerto}|${JSON.stringify(this._mes)}`;
      if (claveMes !== this._claveScroll) {
        this._claveScroll = claveMes;
        this._scrollMes = null; // null = "ir a hoy"
      }
      tabla.addEventListener("scroll", () => {
        if (tabla.clientHeight) this._scrollMes = tabla.scrollTop;
      });
      // La tarjeta puede dibujarse antes de ser visible (alto 0):
      // reintentamos hasta que el navegador la haya colocado.
      const desplazar = (intentos) => {
        if (!tabla.isConnected) return; // ya hay un dibujo más nuevo
        if (!tabla.clientHeight) {
          if (intentos > 0) setTimeout(() => desplazar(intentos - 1), 250);
          return;
        }
        if (this._scrollMes == null) {
          const fila = tabla.querySelector("tr.hoy");
          this._scrollMes = fila ? Math.max(0, fila.offsetTop - tabla.querySelector("thead").offsetHeight - 4) : 0;
        }
        tabla.scrollTop = this._scrollMes;
      };
      requestAnimationFrame(() => desplazar(20));
    }
    raiz.querySelectorAll("[data-nav]").forEach((b) => b.addEventListener("click", () => this._navegar(+b.dataset.nav)));
    // Pulsar un día de la tabla mensual abre ese día.
    raiz.querySelectorAll("tr[data-fecha]").forEach((tr) => tr.addEventListener("click", () => {
      this._fecha = tr.dataset.fecha; this._vista = "dia"; this._render();
    }));
    // Información al pasar el ratón / dedo por el gráfico.
    const caja = raiz.querySelector(".caja-grafico");
    if (caja && this._hover) {
      const svg = caja.querySelector("svg"), tip = caja.querySelector(".tooltip");
      const cur = svg.querySelector(".cursor"), punto = svg.querySelector(".cursor-punto");
      const { curva, sx, sy, fmt, W } = this._hover;
      const mover = (ev) => {
        const r = svg.getBoundingClientRect();
        const xv = ((ev.clientX - r.left) / r.width) * W;
        let mejor = curva[0];
        for (const q of curva) if (Math.abs(sx(q[0]) - xv) < Math.abs(sx(mejor[0]) - xv)) mejor = q;
        const px = sx(mejor[0]), py = sy(mejor[1]);
        cur.setAttribute("x1", px); cur.setAttribute("x2", px); cur.style.display = "";
        punto.setAttribute("cx", px); punto.setAttribute("cy", py); punto.style.display = "";
        tip.textContent = fmt(mejor);
        tip.style.display = "block";
        const left = (px / W) * r.width;
        tip.style.left = `${Math.min(Math.max(left, 60), r.width - 60)}px`;
      };
      svg.addEventListener("pointermove", mover);
      svg.addEventListener("pointerdown", mover);
      svg.addEventListener("pointerleave", () => { tip.style.display = "none"; cur.style.display = "none"; punto.style.display = "none"; });
    }
  }

  _navegar(n) {
    const tz = this._hass.config?.time_zone;
    const p = this._puertoActual();
    const hoy = this._estado(p, "mareas_hoy")?.attributes?.fecha || fechaHoy(tz);
    if (this._vista === "dia") {
      this._fecha = n === 0 ? null : sumarDias(this._fecha || hoy, n);
      if (this._fecha === hoy) this._fecha = null;
    } else {
      const base = this._mes || { anio: +hoy.slice(0, 4), mes: +hoy.slice(5, 7) };
      this._mes = n === 0 ? null : sumarMeses(base.anio, base.mes, n);
    }
    this._render();
  }
}

const CSS = `
  :host { display: block; --mareas-agua: var(--primary-color, #03a9f4); --mareas-pleamar: var(--info-color, #039be5); --mareas-bajamar: var(--warning-color, #ff9800); }
  ha-card { padding: 12px 16px 16px; overflow: hidden; }
  .cab { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; }
  .titulo { font-size: 1.15em; font-weight: 500; color: var(--primary-text-color); }
  select.puerto { font: inherit; color: inherit; background: transparent; border: 1px solid var(--divider-color); border-radius: 6px; padding: 2px 4px; }
  .pestanas { display: inline-flex; border: 1px solid var(--divider-color); border-radius: 18px; overflow: hidden; }
  .pestanas button { font: inherit; font-size: .9em; border: 0; background: transparent; color: var(--primary-text-color); padding: 4px 14px; cursor: pointer; }
  .pestanas button.activa { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .nav { display: flex; align-items: center; gap: 6px; margin: 8px 0 4px; }
  .nav .periodo { flex: 1; text-align: center; color: var(--secondary-text-color); }
  .nav .periodo::first-letter, td.d::first-letter { text-transform: uppercase; }
  .nav button { font: inherit; cursor: pointer; border: 1px solid var(--divider-color); background: transparent; color: var(--primary-text-color); border-radius: 6px; padding: 2px 8px; }
  .nav button.hoy { color: var(--primary-color); }
  .ahora-txt { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; margin: 4px 0; }
  .ahora-txt .grande { font-size: 1.8em; font-weight: 400; color: var(--primary-text-color); }
  .subiendo { color: var(--mareas-pleamar); } .bajando { color: var(--mareas-bajamar); }
  .sec { color: var(--secondary-text-color); }
  .caja-grafico { position: relative; }
  svg.grafico { width: 100%; height: auto; display: block; touch-action: pan-y; }
  .rejilla { stroke: var(--divider-color, #ddd); stroke-width: 1; vector-effect: non-scaling-stroke; }
  .rejilla.v { stroke-dasharray: 2 3; }
  .eje { fill: var(--secondary-text-color); font-size: 11px; }
  .curva { fill: none; stroke: var(--mareas-agua); stroke-width: 2; vector-effect: non-scaling-stroke; }
  .curva.fina { stroke-width: 1; }
  .banda { fill: var(--mareas-agua); opacity: .12; }
  .punto { stroke: var(--card-background-color, #fff); stroke-width: 1.5; vector-effect: non-scaling-stroke; }
  .punto.pleamar, .etq.pleamar { fill: var(--mareas-pleamar); } .punto.bajamar, .etq.bajamar { fill: var(--mareas-bajamar); }
  .etq { font-size: 11px; font-weight: 500; }
  .ahora { stroke: var(--error-color, #db4437); stroke-width: 1.5; stroke-dasharray: 4 3; vector-effect: non-scaling-stroke; }
  .ahora-punto { fill: var(--error-color, #db4437); stroke: var(--card-background-color, #fff); stroke-width: 2; vector-effect: non-scaling-stroke; }
  .cursor { stroke: var(--secondary-text-color); stroke-width: 1; vector-effect: non-scaling-stroke; }
  .cursor-punto { fill: var(--primary-text-color); }
  .tooltip { display: none; position: absolute; top: 0; transform: translateX(-50%); background: var(--card-background-color, #fff); color: var(--primary-text-color); border: 1px solid var(--divider-color); border-radius: 6px; padding: 2px 8px; font-size: 12px; pointer-events: none; white-space: nowrap; }
  .nota { font-size: 11px; color: var(--secondary-text-color); text-align: right; }
  .lista { list-style: none; margin: 8px 0 0; padding: 0; display: grid; gap: 2px; }
  .lista li { display: grid; grid-template-columns: 1.4em 1fr auto 5em; align-items: center; padding: 6px 4px; border-bottom: 1px solid var(--divider-color); color: var(--primary-text-color); }
  .lista li:last-child { border-bottom: 0; }
  .lista .flecha { font-size: .9em; } .lista .pleamar .flecha { color: var(--mareas-pleamar); } .lista .bajamar .flecha { color: var(--mareas-bajamar); }
  .lista .hora { font-weight: 500; font-variant-numeric: tabular-nums; } .lista .alt { text-align: right; color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
  .tabla-mes { max-height: 340px; overflow-y: auto; margin-top: 8px; }
  table { width: 100%; border-collapse: collapse; font-size: .9em; color: var(--primary-text-color); font-variant-numeric: tabular-nums; }
  th { position: sticky; top: 0; background: var(--card-background-color, #fff); font-weight: 500; text-align: left; padding: 4px; border-bottom: 1px solid var(--divider-color); }
  th.pleamar { color: var(--mareas-pleamar); } th.bajamar { color: var(--mareas-bajamar); }
  td { padding: 4px; border-bottom: 1px solid var(--divider-color); vertical-align: top; }
  td span { display: block; } td small { color: var(--secondary-text-color); }
  td.d { white-space: nowrap; color: var(--secondary-text-color); } td.c { color: var(--secondary-text-color); }
  tr[data-fecha] { cursor: pointer; } tr[data-fecha]:hover { background: rgba(127,127,127,.08); }
  tr.hoy td { background: rgba(3,169,244,.12); font-weight: 500; }
  .aviso { padding: 16px 0; color: var(--secondary-text-color); text-align: center; }
`;

/* ------------------------------------------------------------------ */
/*  Editor visual (lo que ves al pulsar "Editar" en la tarjeta)          */
/* ------------------------------------------------------------------ */
class MareasCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._pintar();
  }

  set hass(hass) {
    this._hass = hass;
    this._pintar();
  }

  _pintar() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (s) => ({
        puerto: "Puerto", vista: "Vista inicial", mostrar: "Mostrar",
        selector_puerto: "Permitir cambiar de puerto", titulo: "Título",
      })[s.name] || s.name;
      this._form.addEventListener("value-changed", (ev) => {
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: ev.detail.value }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    // Los puertos los sacamos de los dispositivos creados por la integración
    // (reutilizamos la misma función de búsqueda que la tarjeta).
    const puertos = MareasCard.prototype._puertos.call({ _hass: this._hass });
    this._form.schema = [
      { name: "puerto", selector: { select: { mode: "dropdown", options: puertos.map((p) => ({ value: p.id, label: p.nombre })) } } },
      { name: "vista", selector: { select: { mode: "dropdown", options: [{ value: "dia", label: "Día" }, { value: "mes", label: "Mes" }] } } },
      { name: "mostrar", selector: { select: { mode: "dropdown", options: [
        { value: "ambos", label: "Texto y gráfico" }, { value: "texto", label: "Solo texto" }, { value: "grafico", label: "Solo gráfico" }] } } },
      { name: "selector_puerto", selector: { boolean: {} } },
      { name: "titulo", selector: { text: {} } },
    ];
    this._form.hass = this._hass;
    this._form.data = this._config;
  }
}

if (!customElements.get("mareas-card")) customElements.define("mareas-card", MareasCard);
if (!customElements.get("mareas-card-editor")) customElements.define("mareas-card-editor", MareasCardEditor);

// Para que aparezca en el selector "Añadir tarjeta" de los paneles.
window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "mareas-card")) {
  window.customCards.push({
    type: "mareas-card",
    name: "Mareas",
    description: "Pleamares y bajamares del día o del mes, en texto y gráfico (Mareas IHM).",
    preview: true,
    documentationURL: "https://github.com/pqrs/ha-mareas-ihm",
  });
}

console.info(`%c MAREAS-CARD %c ${VERSION} `, "background:#0277bd;color:#fff;border-radius:3px 0 0 3px", "background:#e1f5fe;color:#01579b;border-radius:0 3px 3px 0");

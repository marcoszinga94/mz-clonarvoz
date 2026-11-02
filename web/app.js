// ClonarVoz — interfaz local. Sin dependencias, sin build.

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

const fmt = (s) => {
  s = Math.max(0, Math.round(s));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};
const bonito = (n) =>
  String(n).replace(/\.[^.]+$/, "").replace(/-\d+$/, "").replace(/[-_]+/g, " ").trim();

const hora = (t) => {
  const d = new Date(t * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};

const esc = (t) =>
  String(t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let det = `error ${r.status}`;
    try { det = (await r.json()).detail || det; } catch (_) {}
    throw new Error(det);
  }
  return r.json();
}

const estado = {
  refs: [], motor: "cargando", job: null, timer: null, polling: null, grabando: null,
  colaDOM: new Map(), colaTimer: null, sinRef: false,
  stream: { cola: [], vistos: 0, job: null, resultados: 0 },
  jobActual: null, cancelando: new Set(),
};

function toast(msg, malo = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.toggle("error", malo);
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.hidden = true; }, 4200);
}

function errorGuion(msg) {
  const e = $("#error-guion");
  e.textContent = msg;
  e.hidden = !msg;
}

// --------------------------------------------------------------- estado

async function cargarEstado() {
  try {
    const e = await api("/api/estado");
    estado.motor = e.motor;
    pintarMotor(e);
    pintarRefs(e.refs);
    estado.motores = e.motores || {};
    pintarMotores();
  } catch (_) {
    pintarMotor({ motor: "error", error: "no responde el servidor" });
  }
  clearTimeout(cargarEstado._t);
  cargarEstado._t = setTimeout(cargarEstado, estado.motor === "listo" ? 15000 : 2000);
}

const MOTOR_TEXTO = {
  chatterbox: "Chatterbox: clona timbre y ritmo. Más lento, más parecido.",
  openvoice: "OpenVoice V2: clona el timbre. Más rápido, solo español.",
};

function pintarMotores() {
  const sel = $("#motor");
  const op = sel.querySelector('option[value="openvoice"]');
  const listo = Boolean(estado.motores && estado.motores.openvoice);
  op.disabled = !listo;
  op.textContent = listo ? "OpenVoice V2 (español)" : "OpenVoice V2 (no instalado)";
  if (!listo && sel.value === "openvoice") sel.value = "chatterbox";
  aplicarMotor();
}

function aplicarMotor() {
  const ov = $("#motor").value === "openvoice";
  $("#motor-nota").textContent = MOTOR_TEXTO[ov ? "openvoice" : "chatterbox"];
}

function pintarMotor(e) {
  const dot = $("#dot");
  const txt = $("#estado-txt");  dot.className = "dot " + (e.motor === "listo" ? "listo" : e.motor === "error" ? "error" : "cargando");
  if (e.motor === "listo") txt.textContent = "Motor listo";
  else if (e.motor === "error") txt.textContent = "Motor con error";
  else txt.textContent = "Cargando modelo";
  estado.motor = e.motor;
  aplicarSinRef(Boolean(estado.sinRef));
  if (estado.sinRef) return;
  $("#btn-generar").disabled = e.motor !== "listo";
  $("#btn-generar").title = e.motor === "listo" ? "" : "El modelo todavía se está cargando";
}

// Sin referencia no hay clon: el estudio no genera voces nuevas.
function aplicarSinRef(sin) {
  estado.sinRef = sin;
  const btn = $("#btn-generar");
  const nota = $("#sin-ref-nota");
  if (nota) nota.hidden = !sin;
  if (sin) {
    btn.disabled = true;
    btn.title = "Grabá o subí tu voz: este estudio clona, no genera voces nuevas";
  } else if (estado.motor === "listo") {
    btn.disabled = false;
    btn.title = "";
  }
}

let _refsFirma = "";

let ajustesListos = false;

async function cargarAjustes() {
  try {
    estado.ajustes = await api("/api/ajustes");
  } catch (_) {
    estado.ajustes = {};
  }
  ajustesListos = true;
  aplicarAjustes();
}

function aplicarAjustes() {
  if (!ajustesListos) return;
  const m = estado.ajustes.motor;
  const sel = $("#motor");
  const op = m ? sel.querySelector(`option[value="${m}"]`) : null;
  if (op && !op.disabled) {
    sel.value = m;
    aplicarMotor();
  }
  const fid = String(estado.ajustes.fidelidad || 1);
  const selFid = $("#fidelidad");
  if (selFid && [...selFid.options].some((o) => o.value === fid)) selFid.value = fid;

  const guardada = estado.ajustes.ref;
  if (guardada && estado.refs.some((r) => r.nombre === guardada) && $("#select-voz").value !== guardada) {
    _refsFirma = "";          // fuerza el repintado del selector
    pintarRefs(estado.refs);
  }
}

async function guardarAjustes() {
  try {
    await api("/api/ajustes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        motor: $("#motor").value,
        ref: $("#select-voz").value || null,
        fidelidad: parseInt($("#fidelidad").value || "1", 10),
      }),
    });
  } catch (_) {}
}

function pintarRefs(refs) {
  estado.refs = refs;

  // El estado se refresca cada 15 s: si nada cambió, no se toca el DOM ni el
  // reproductor (reasignar `src` corta la reproducción en curso).
  const firma = refs.map((r) => [r.nombre, r.dur, r.mtime, r.exag ?? ""].join("|")).join(",");
  if (firma === _refsFirma) return;
  _refsFirma = firma;

  const sel = $("#select-voz");
  const antes = sel.value;
  sel.innerHTML = "";
  if (!refs.length) {
    // Sin referencia no hay clon: no se ofrece "voz por defecto".
    sel.append(new Option("Grabá o subí tu voz para empezar", ""));
    sel.disabled = true;
  } else {
    sel.disabled = false;
    refs.forEach((r) => {
      const sello = r.mtime ? ` · ${hora(r.mtime)}` : "";
      const nota = r.nota != null ? ` · ${r.nota.toFixed(2)}` : "";
      sel.append(new Option(`${bonito(r.nombre)} · ${fmt(r.dur)}${nota}${sello}`, r.nombre));
    });
    const conNota = refs.filter((r) => r.nota != null);
    const mejor = conNota.length ? conNota.reduce((a, b) => (b.nota > a.nota ? b : a)) : refs[0];
    // La toma guardada manda, salvo que clonе claramente peor que otra:
    // con fidelidad como prioridad, no tiene sentido arrancar con la peor.
    let guardada = ajustesListos && estado.ajustes.ref
      ? refs.find((r) => r.nombre === estado.ajustes.ref) : null;
    if (guardada && mejor.nota != null && guardada.nota != null
        && guardada.nota < mejor.nota - 0.03) {
      guardada = null;
    }
    const elegido = refs.find((r) => r.nombre === antes) || guardada || mejor;
    sel.value = elegido.nombre;
  }
  pintarRefAudio();
}

function pintarRefAudio() {
  const nombre = $("#select-voz").value;
  const ref = estado.refs.find((r) => r.nombre === nombre);
  const audio = $("#ref-audio");
  aplicarSinRef(!ref);
  if (!ref) {
    audio.hidden = true;
    $("#ref-dur").textContent = "";
    $("#btn-calibrar").hidden = true;
    $("#ref-veredicto").hidden = true;
    return;
  }
  audio.hidden = false;
  // `?v=` fuerza recarga cuando se regraba con el mismo nombre, y evita
  // recargar (y cortar) el audio cuando el archivo no cambió.
  const url = new URL(`${ref.url}?v=${Math.round(ref.mtime || 0)}`, location.href).href;
  if (audio.src !== url) audio.src = url;
  $("#ref-dur").textContent = fmt(ref.dur);
  $("#btn-calibrar").hidden = false;
  $("#btn-evaluar").hidden = estado.refs.length < 2;
  pintarAnalisis(ref.analisis);
}

function pintarAnalisis(a) {
  const el = $("#ref-veredicto");
  if (!a) { el.hidden = true; return; }
  const partes = [];
  if (a.snr_db != null) partes.push(`SNR ${a.snr_db} dB`);
  if (a.silencio_pct != null) partes.push(`${a.silencio_pct}% silencio`);
  partes.push(`${a.dur}s`);
  el.textContent = a.avisos && a.avisos.length
    ? a.avisos.join(" · ")
    : `Referencia en buen estado · ${partes.join(" · ")}`;
  el.className = `pista ${a.veredicto || "ok"}`;
  el.hidden = false;
}

// --------------------------------------------------------------- grabar

async function empezarGrabacion() {
  if (!navigator.mediaDevices || !window.MediaRecorder) {
    toast("Este navegador no permite grabar. Usa Subir.", true);
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus" : "";
    const media = new MediaRecorder(stream, mime ? { mimeType: mime, audioBitsPerSecond: 128000 } : undefined);
    const g = { stream, media, chunks: [], t0: performance.now(), iv: null, tope: null };
    estado.grabando = g;

    media.ondataavailable = (ev) => { if (ev.data.size) g.chunks.push(ev.data); };
    media.onstop = () => finalizarGrabacion(g);
    media.start(250);

    $("#modal").hidden = false;
    $("#modal-tiempo").textContent = "0:00";
    g.iv = setInterval(() => {
      const s = (performance.now() - g.t0) / 1000;
      $("#modal-tiempo").textContent = fmt(s);
    }, 100);
  } catch (err) {
    toast("No pude abrir el micrófono: " + err.message, true);
  }
}

function detenerGrabacion() {
  const g = estado.grabando;
  if (!g || g.media.state === "inactive") return;
  clearInterval(g.iv);
  g.media.stop();
}

function cancelarGrabacion() {
  const g = estado.grabando;
  if (!g) return;
  clearInterval(g.iv);
  g.media.onstop = null;
  if (g.media.state !== "inactive") g.media.stop();
  g.stream.getTracks().forEach((t) => t.stop());
  estado.grabando = null;
  $("#modal").hidden = true;
}

async function finalizarGrabacion(g) {
  clearInterval(g.iv);
  g.stream.getTracks().forEach((t) => t.stop());
  estado.grabando = null;
  $("#modal").hidden = true;

  const blob = new Blob(g.chunks, { type: g.media.mimeType || "audio/webm" });
  if (blob.size < 3000) { toast("La grabación quedó vacía. Prueba otra vez.", true); return; }
  await subirReferencia(blob, "toma.webm", "mi-voz");
}

async function subirReferencia(blob, nombre, etiqueta) {
  const datos = new FormData();
  datos.append("archivo", blob, nombre);
  datos.append("nombre", etiqueta);
  toast("Limpiando la referencia");
  try {
    const r = await api("/api/ref", { method: "POST", body: datos });
    const extra = r.total && r.total > r.dur + 1 ? ` de ${fmt(r.total)} grabados` : "";
    toast(`Referencia lista: ${fmt(r.dur)}${extra}`);
    await cargarEstado();
    $("#select-voz").value = r.nombre;
    pintarRefAudio();
    $("#ref-audio").play().catch(() => {});
  } catch (e) {
    toast(String(e.message), true);
  }
}

// --------------------------------------------------------------- generar

function tituloDe(texto, i) {
  const t = texto.replace(/\s+/g, " ").trim();
  return t.length > 60 ? t.slice(0, 60).trimEnd() : (t || `Clip ${i + 1}`);
}

function actualizarContador() {
  const t = $("#guion").value.trim();
  const palabras = t ? t.split(/\s+/).length : 0;
  $("#contador").textContent = `${palabras} palabra${palabras === 1 ? "" : "s"} · ~${fmt(palabras / 2.6)}`;
}

async function generar() {
  errorGuion("");
  const lineas = $("#guion").value.split(/\n+/).map((l) => l.trim()).filter(Boolean);
  if (!lineas.length) {
    errorGuion("Escribe al menos una línea de guion.");
    $("#guion").focus();
    return;
  }
  if (estado.motor !== "listo") {
    errorGuion("El modelo todavía se está cargando. Espera al indicador verde.");
    return;
  }
  if (!$("#select-voz").value) {
    errorGuion("Grabá o subí tu voz primero: este estudio clona, no genera voces nuevas.");
    return;
  }

  const items = lineas.map((texto, i) => ({ nombre: tituloDe(texto, i), texto }));
  // Solo se elige motor y referencia: el resto lo resuelve el servidor con los
  // valores calibrados de la toma.
  const body = {
    items,
    ref: $("#select-voz").value,
    motor: $("#motor").value,
    fidelidad: parseInt($("#fidelidad").value || "1", 10),
  };

  // No se bloquea el botón: se puede encolar otro guion mientras este se genera.
  try {
    await api("/api/generar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    toast(`En cola: ${items.length} clip${items.length === 1 ? "" : "s"}`);
    await refrescarCola();
  } catch (e) {
    errorGuion(String(e.message));
  }
}

function reiniciarStream() {
  const a = $("#stream-audio");
  a.pause();
  a.removeAttribute("src");
  a.hidden = true;
  estado.stream = { cola: [], vistos: 0, job: null, resultados: 0 };
  $("#preview-gen").hidden = true;
}

function siguienteAudio() {
  const a = $("#stream-audio");
  const url = estado.stream.cola.shift();
  if (!url) return;
  a.src = url;
  a.hidden = false;
  a.play().catch(() => {});
}

function encolarAudio(url) {
  estado.stream.cola.push(url);
  if ($("#stream-audio").paused) siguienteAudio();
}

$("#stream-audio").addEventListener("ended", () => {
  if (estado.stream.cola.length) siguienteAudio();
});

function prepararTrabajo(titulo, detalle) {
  reiniciarStream();
  $("#trabajo").hidden = false;
  $("#trabajo-titulo").textContent = titulo;
  $("#trabajo-detalle").textContent = detalle;
  $("#barra-fill").style.width = "2%";
  $("#spin").hidden = false;

  const t0 = performance.now();
  clearInterval(estado.timer);
  estado.timer = setInterval(() => {
    $("#trabajo-tiempo").textContent = fmt((performance.now() - t0) / 1000);
  }, 500);
}

const COLA_ESTADOS = { en_cola: "En cola", generando: "Generando", listo: "Listo",
                       error: "Error", cancelado: "Cancelado" };

function plantillaCola(j) {
  const titulo = j.n_items === 1 ? "1 clip" : `${j.n_items} clips`;
  const motor = j.motor === "openvoice" ? "OpenVoice" : "Chatterbox";
  return `<div class="cola-item" data-estado="${j.estado}">
    <div class="cola-h">
      <span class="cola-t">${esc(titulo)}</span>
      <span class="clip-tag" data-motor="${esc(j.motor || "chatterbox")}">${motor}</span>
      <span class="cola-badge">${COLA_ESTADOS[j.estado] || j.estado}</span>
      <span class="mono hint cola-tiempo">0:00</span>
      <button class="btn btn-mini btn-cancelar-cola" data-cancelar="${j.id}" type="button" hidden>Cancelar</button>
    </div>
    <div class="barra"><span></span></div>
    <p class="cola-detalle">En cola</p>
  </div>`;
}

async function refrescarCola() {
  clearTimeout(estado.colaTimer);
  try {
    const r = await api("/api/trabajos");
    pintarCola(r.trabajos || []);
    if ((r.trabajos || []).some((j) => j.estado === "en_cola" || j.estado === "generando")) {
      estado.colaTimer = setTimeout(refrescarCola, 1500);
    }
  } catch (_) {
    estado.colaTimer = setTimeout(refrescarCola, 5000);
  }
}

const enMarcha = (j) => j.estado === "en_cola" || j.estado === "generando";

function pintarCola(todos) {
  const activos = todos.filter(enMarcha);
  const cont = $("#cola");
  $("#cola-card").hidden = activos.length === 0;

  if (!activos.length) {
    cont.innerHTML = "";
    estado.colaDOM.clear();
    $("#cola-resumen").textContent = "";
    if (estado.stream.job) reiniciarStream();
    return;
  }

  // Los que ya no están activos se sacan de la lista: quedan en "Ya generados".
  let refrescarLista = false;
  estado.colaDOM.forEach((nodo, id) => {
    if (activos.some((j) => j.id === id)) return;
    const fin = todos.find((j) => j.id === id);
    if (fin && fin.estado === "error") toast(fin.error || "No se pudo generar", true);
    if (fin && (fin.estado === "listo" || fin.estado === "cancelado")) refrescarLista = true;
    nodo.remove();
    estado.colaDOM.delete(id);
  });

  const generando = activos.filter((j) => j.estado === "generando").length;
  const espera = activos.length - generando;
  const partes = [];
  if (generando) partes.push("generando ahora");
  if (espera) partes.push(`${espera} en espera`);
  $("#cola-resumen").textContent = partes.join(" · ");

  const ahora = Date.now() / 1000;
  activos.forEach((j) => {
    let nodo = estado.colaDOM.get(j.id);
    if (!nodo) {
      cont.insertAdjacentHTML("beforeend", plantillaCola(j));
      nodo = cont.lastElementChild;
      estado.colaDOM.set(j.id, nodo);
    }
    nodo.dataset.estado = j.estado;
    nodo.querySelector(".cola-badge").textContent = COLA_ESTADOS[j.estado] || j.estado;
    nodo.querySelector(".barra span").style.width = `${Math.max(2, Math.round((j.progreso || 0) * 100))}%`;
    nodo.querySelector(".cola-detalle").textContent = j.estado === "error"
      ? (j.error || "error desconocido") : (j.detalle || "");
    nodo.querySelector(".cola-tiempo").textContent =
      j.estado === "en_cola" ? "—"
        : fmt(j.segundos != null ? j.segundos : ahora - (j.inicio || ahora));

    const btnCancelar = nodo.querySelector("[data-cancelar]");
    const cancelando = estado.cancelando.has(j.id);
    btnCancelar.hidden = false;
    btnCancelar.disabled = cancelando;
    btnCancelar.textContent = cancelando ? "Cancelando…" : "Cancelar";
  });

  // Vista previa: suena cada frase a medida que el modelo la termina.
  const gen = activos.find((j) => j.estado === "generando");
  if (gen) {
    if (estado.stream.job !== gen.id) {
      reiniciarStream();
      estado.stream.job = gen.id;
    }
    (gen.parciales || []).slice(estado.stream.vistos).forEach((p) => encolarAudio(p.url));
    estado.stream.vistos = (gen.parciales || []).length;
    $("#preview-gen").hidden = !estado.stream.vistos;
    $("#preview-gen-txt").textContent = estado.stream.vistos
      ? `Escuchando mientras se genera · ${estado.stream.vistos} frase${estado.stream.vistos === 1 ? "" : "s"}`
      : "Escuchando mientras se genera";

    // Los clips van apareciendo en la biblioteca a medida que se cierran.
    const hechos = (gen.resultados || []).length;
    if (hechos !== estado.stream.resultados) {
      estado.stream.resultados = hechos;
      if (hechos) refrescarLista = true;
    }
  }

  if (refrescarLista) cargarBiblioteca();
}

// --------------------------------------------------------------- biblioteca

async function cargarBiblioteca() {
  try {
    const { clips } = await api("/api/historial");
    const lista = $("#lista");
    lista.innerHTML = clips.map(filaBiblioteca).join("");
    $("#vacio").hidden = clips.length > 0;
    $("#biblio-count").textContent = clips.length ? `${clips.length} clip${clips.length === 1 ? "" : "s"}` : "";
  } catch (_) {}
}

function filaBiblioteca(c) {
  const fecha = new Date(c.mtime * 1000);
  const cuando = fecha.toLocaleDateString("es", { day: "2-digit", month: "short" }) + " · " +
    fecha.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" });
  const motor = c.motor === "openvoice" ? "OpenVoice" : "Chatterbox";
  const variante = { argentina: "argentino", latam: "LatAm", espana: "España" }[c.variante] || "";
  return `<div class="clip">
    <div>
      <div class="clip-top">
        <span class="clip-t">${esc(c.titulo || bonito(c.nombre))}</span>
        <span class="clip-tag" data-motor="${esc(c.motor || "chatterbox")}" title="Motor de clonación">${motor}${variante ? ` · ${variante}` : ""}</span>
      </div>
      <div class="clip-m mono">${fmt(c.dur)} · ${cuando}</div>
    </div>
    <div class="clip-acc">
      ${c.mp4
        ? `<a class="icon-btn" href="${c.mp4}" download title="Descargar video 9:16" aria-label="Descargar video 9:16">
             <svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="3" width="10" height="18" rx="2"/><path d="m11 10.5 3 1.5-3 1.5z"/></svg>
           </a>`
        : `<button class="icon-btn" data-video="${c.nombre}" title="Crear video 9:16" aria-label="Crear video 9:16">
             <svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="3" width="10" height="18" rx="2"/><path d="m11 10.5 3 1.5-3 1.5z"/></svg>
           </button>`}
      <a class="icon-btn" href="${c.mp3}" download title="Descargar MP3" aria-label="Descargar MP3">
        <svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v12m0 0 4-4m-4 4-4-4"/><path d="M4 18v1a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-1"/></svg>
      </a>
      ${c.srt ? `<a class="icon-btn" href="${c.srt}" download title="Descargar subtítulos" aria-label="Descargar subtítulos">
        <svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 15h4M13 15h4M7 11h2M11 11h6"/></svg>
      </a>` : ""}
      <button class="icon-btn borrar" data-borrar="${c.nombre}" title="Borrar" aria-label="Borrar clip">
        <svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-12"/></svg>
      </button>
    </div>
    <audio controls preload="none" src="${c.mp3}"></audio>
  </div>`;
}

async function borrar(nombre) {
  if (!confirm("¿Borrar este clip y sus subtítulos?")) return;
  try {
    await api(`/api/historial/${nombre}`, { method: "DELETE" });
    cargarBiblioteca();
  } catch (e) {
    toast(String(e.message), true);
  }
}

// --------------------------------------------------------------- guiones

const guionUI = { objetivo: "educar", segundos: 30, variante: 0 };

function abrirGuion() {
  guionUI.variante = 0;
  $("#modal-guion").hidden = false;
  $("#btn-guion").setAttribute("aria-expanded", "true");
  $("#g-error").hidden = true;
  $("#g-otra").hidden = true;
  $("#g-preview").hidden = true;
  $("#g-crear").textContent = "Crear guion";
  setTimeout(() => $("#gtema").focus(), 80);
}

function cerrarGuion() {
  $("#modal-guion").hidden = true;
  $("#btn-guion").setAttribute("aria-expanded", "false");
  $("#btn-guion").focus();
}

function errorModal(msg) {
  const e = $("#g-error");
  e.textContent = msg;
  e.hidden = false;
}

async function crearGuion(otra) {
  const tema = $("#gtema").value.trim();
  if (!tema) {
    errorModal("Escribe un tema para el guion.");
    $("#gtema").focus();
    return;
  }
  guionUI.variante = otra ? guionUI.variante + 1 : 0;
  $("#g-crear").disabled = true;
  try {
    const r = await api("/api/guion", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tema,
        objetivo: guionUI.objetivo,
        segundos: guionUI.segundos,
        variante: guionUI.variante,
      }),
    });
    $("#guion").value = r.lineas.join("\n");
    actualizarContador();
    $("#g-preview").innerHTML =
      r.lineas.map((l) => `<p>${esc(l)}</p>`).join("") +
      `<p class="mono">${r.palabras} palabras · ~${fmt(r.duracion_estimada)}</p>`;
    $("#g-preview").hidden = false;
    $("#g-otra").hidden = false;
    $("#g-crear").textContent = "Usar este guion";
    $("#g-error").hidden = true;
  } catch (e) {
    errorModal(String(e.message));
  } finally {
    $("#g-crear").disabled = false;
  }
}

function conectarChips(sel, clave, numerico) {
  $(sel).addEventListener("click", (e) => {
    const b = e.target.closest(".chip");
    if (!b) return;
    $$(".chip", $(sel)).forEach((x) => {
      const on = x === b;
      x.classList.toggle("activo", on);
      x.setAttribute("aria-pressed", on ? "true" : "false");
    });
    guionUI[clave] = numerico ? Number(b.dataset.v) : b.dataset.v;
  });
}

// --------------------------------------------------------------- calibrar

async function calibrar() {
  const nombre = $("#select-voz").value;
  if (!nombre) return;
  prepararTrabajo("Calibrando la voz", "Probando la toma");
  $("#btn-calibrar").disabled = true;
  try {
    const r = await api("/api/ref/calibrar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nombre, motor: $("#motor").value }),
    });
    seguirCalibracion(r.job);
  } catch (e) {
    $("#btn-calibrar").disabled = false;
    $("#trabajo").hidden = true;
    toast(String(e.message), true);
  }
}

function seguirCalibracion(jobId) {
  prepararTrabajo("Calibrando la voz", "Probando expresividades");
  estado.jobActual = jobId;
  $("#btn-cancelar-job").hidden = false;
  $("#btn-cancelar-job").disabled = false;
  clearTimeout(estado.polling);

  const tick = async () => {
    try {
      const j = await api(`/api/job/${jobId}`);
      $("#barra-fill").style.width = `${Math.max(2, Math.round(j.progreso * 100))}%`;
      $("#trabajo-detalle").textContent = j.detalle || "";

      if (j.estado === "listo" && j.calibracion) {
        clearInterval(estado.timer);
        clearTimeout(estado.polling);
        $("#spin").hidden = true;
        $("#btn-cancelar-job").hidden = true;
        $("#btn-calibrar").disabled = false;
        estado.jobActual = null;
        const m = j.calibracion.mejor;
        $("#trabajo-titulo").textContent = "Voz calibrada";
        $("#trabajo-detalle").textContent =
          `Similitud ${m.sim} · tono ${m.f0} Hz${m.tau != null ? ` · fidelidad ${Number(m.tau).toFixed(2)}` : ""}`;
        $("#barra-fill").style.width = "100%";
        cargarEstado();
        toast("Calibración guardada en la referencia");
        return;
      }
      if (j.estado === "cancelado" || j.estado === "error") {
        clearInterval(estado.timer);
        clearTimeout(estado.polling);
        $("#spin").hidden = true;
        $("#btn-cancelar-job").hidden = true;
        $("#btn-calibrar").disabled = false;
        estado.jobActual = null;
        $("#trabajo-titulo").textContent = j.estado === "error" ? "No se pudo calibrar" : "Calibración cancelada";
        $("#trabajo-detalle").textContent = j.error || "";
        return;
      }
      estado.polling = setTimeout(tick, 1200);
    } catch (e) {
      clearInterval(estado.timer);
      $("#btn-calibrar").disabled = false;
      toast(String(e.message), true);
    }
  };
  estado.polling = setTimeout(tick, 600);
}

// --------------------------------------------------------------- evaluar tomas

async function evaluarTomas() {
  prepararTrabajo("Evaluando tomas", "Comparando con tu voz");
  $("#btn-evaluar").disabled = true;
  try {
    const r = await api("/api/ref/evaluar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ motor: $("#motor").value }),
    });
    seguirEvaluacion(r.job);
  } catch (e) {
    $("#btn-evaluar").disabled = false;
    $("#trabajo").hidden = true;
    toast(String(e.message), true);
  }
}

function seguirEvaluacion(jobId) {
  prepararTrabajo("Evaluando tomas", "Midiendo cada referencia");
  estado.jobActual = jobId;
  $("#btn-cancelar-job").hidden = false;
  $("#btn-cancelar-job").disabled = false;
  clearTimeout(estado.polling);

  const tick = async () => {
    try {
      const j = await api(`/api/job/${jobId}`);
      $("#barra-fill").style.width = `${Math.max(2, Math.round(j.progreso * 100))}%`;
      $("#trabajo-detalle").textContent = j.detalle || "";

      if (j.estado === "listo" && j.evaluacion) {
        clearInterval(estado.timer);
        clearTimeout(estado.polling);
        $("#spin").hidden = true;
        $("#btn-cancelar-job").hidden = true;
        $("#btn-evaluar").disabled = false;
        estado.jobActual = null;
        const tomas = j.evaluacion.tomas;
        $("#trabajo-titulo").textContent = "Mejor toma elegida";
        $("#trabajo-detalle").textContent =
          tomas.map((t) => `${t.ref.replace(".wav", "")}: ${t.score.toFixed(2)}`).join(" · ");
        $("#barra-fill").style.width = "100%";
        if (j.evaluacion.mejor) {
          $("#select-voz").value = j.evaluacion.mejor;
          pintarRefAudio();
          toast(`Usando ${bonito(j.evaluacion.mejor)} (${tomas[0].score.toFixed(2)})`);
        }
        cargarEstado();
        return;
      }
      if (j.estado === "cancelado" || j.estado === "error") {
        clearInterval(estado.timer);
        clearTimeout(estado.polling);
        $("#spin").hidden = true;
        $("#btn-cancelar-job").hidden = true;
        $("#btn-evaluar").disabled = false;
        estado.jobActual = null;
        $("#trabajo-titulo").textContent = "Evaluación cancelada";
        $("#trabajo-detalle").textContent = j.error || "";
        return;
      }
      estado.polling = setTimeout(tick, 1200);
    } catch (e) {
      clearInterval(estado.timer);
      $("#btn-evaluar").disabled = false;
      toast(String(e.message), true);
    }
  };
  estado.polling = setTimeout(tick, 600);
}

// --------------------------------------------------------------- transcribir

async function transcribirArchivo(file) {
  if ($("#guion").value.trim() && !confirm("La transcripción reemplaza el guion actual. ¿Seguir?")) {
    return;
  }
  const datos = new FormData();
  datos.append("archivo", file, file.name);
  datos.append("lang", "es");
  errorGuion("");
  prepararTrabajo("Transcribiendo", "Subiendo audio");
  try {
    const r = await api("/api/transcribir", { method: "POST", body: datos });
    seguirTranscripcion(r.job);
  } catch (e) {
    $("#trabajo").hidden = true;
    toast(String(e.message), true);
  }
}

function seguirTranscripcion(jobId) {
  prepararTrabajo("Transcribiendo", "Preparando modelo");
  estado.jobActual = jobId;
  clearTimeout(estado.polling);

  const tick = async () => {
    try {
      const j = await api(`/api/job/${jobId}`);
      $("#barra-fill").style.width = `${Math.max(2, Math.round(j.progreso * 100))}%`;
      $("#trabajo-detalle").textContent = j.detalle || "";

      if (j.estado === "listo") {
        clearInterval(estado.timer);
        clearTimeout(estado.polling);
        $("#spin").hidden = true;
        $("#btn-cancelar-job").hidden = true;
        reiniciarStream();
        estado.jobActual = null;
        $("#trabajo-titulo").textContent = "Transcripción lista";
        $("#trabajo-detalle").textContent =
          `${j.lineas.length} frase${j.lineas.length === 1 ? "" : "s"} · ${fmt(j.dur)} · ${j.idioma}`;
        $("#barra-fill").style.width = "100%";
        $("#guion").value = j.lineas.join("\n");
        actualizarContador();
        $("#guion").focus();
        toast(`Transcrito ${fmt(j.dur)} de audio con Whisper ${j.modelo}`);
        return;
      }
      if (j.estado === "error") {
        clearInterval(estado.timer);
        clearTimeout(estado.polling);
        $("#spin").hidden = true;
        $("#trabajo-titulo").textContent = "No se pudo transcribir";
        $("#trabajo-detalle").textContent = j.error || "error desconocido";
        return;
      }
      estado.polling = setTimeout(tick, 900);
    } catch (e) {
      clearInterval(estado.timer);
      $("#spin").hidden = true;
      $("#trabajo-titulo").textContent = "Se cortó la conexión";
      $("#trabajo-detalle").textContent = String(e.message);
    }
  };
  estado.polling = setTimeout(tick, 400);
}

// --------------------------------------------------------------- eventos

$("#btn-grabar").addEventListener("click", () => {
  if (estado.grabando) detenerGrabacion();
  else empezarGrabacion();
});
$("#btn-detener").addEventListener("click", detenerGrabacion);
$("#btn-cancelar").addEventListener("click", cancelarGrabacion);
$("#btn-subir").addEventListener("click", () => $("#file").click());

$("#file").addEventListener("change", async (ev) => {
  const f = ev.target.files && ev.target.files[0];
  if (!f) return;
  await subirReferencia(f, f.name, f.name.replace(/\.[^.]+$/, "").slice(0, 24) || "voz");
  ev.target.value = "";
});

$("#select-voz").addEventListener("change", () => { pintarRefAudio(); guardarAjustes(); });
$("#motor").addEventListener("change", () => { aplicarMotor(); guardarAjustes(); });
$("#fidelidad").addEventListener("change", guardarAjustes);
$("#guion").addEventListener("input", actualizarContador);
$("#btn-generar").addEventListener("click", generar);
$("#cola").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-cancelar]");
  if (!b) return;
  const id = b.dataset.cancelar;
  estado.cancelando.add(id);
  b.disabled = true;
  b.textContent = "Cancelando…";
  try {
    const r = await api(`/api/job/${id}/cancelar`, { method: "POST" });
    if (!r.ok) toast(`Ese trabajo ya está ${COLA_ESTADOS[r.estado] || r.estado}`, true);
  } catch (err) {
    estado.cancelando.delete(id);
    b.disabled = false;
    b.textContent = "Cancelar";
    toast(String(err.message), true);
  }
  refrescarCola();
});

$("#lista").addEventListener("click", (e) => {
  const b = e.target.closest("[data-borrar]");
  if (b) { borrar(b.dataset.borrar); return; }
  const v = e.target.closest("[data-video]");
  if (v) crearVideo(v.dataset.video, v);
});

async function crearVideo(nombre, boton) {
  boton.disabled = true;
  toast("Generando video 9:16…");
  try {
    const r = await api("/api/video", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nombre }),
    });
    toast(`Video listo · ${fmt(r.dur)}`);
    cargarBiblioteca();
  } catch (e) {
    toast(String(e.message), true);
    boton.disabled = false;
  }
}

$("#btn-cancelar-job").addEventListener("click", async () => {
  const id = estado.jobActual;
  if (!id) return;
  $("#btn-cancelar-job").disabled = true;
  try {
    await api(`/api/job/${id}/cancelar`, { method: "POST" });
    $("#trabajo-detalle").textContent = "Cancelando…";
  } catch (e) {
    toast(String(e.message), true);
    $("#btn-cancelar-job").disabled = false;
  }
});

$("#btn-calibrar").addEventListener("click", calibrar);
$("#btn-evaluar").addEventListener("click", evaluarTomas);
$("#btn-guion").addEventListener("click", abrirGuion);
$("#btn-transcribir").addEventListener("click", () => $("#file-tx").click());
$("#file-tx").addEventListener("change", (ev) => {
  const f = ev.target.files && ev.target.files[0];
  ev.target.value = "";
  if (f) transcribirArchivo(f);
});
$("#g-cancelar").addEventListener("click", cerrarGuion);
$("#g-crear").addEventListener("click", () => {
  if ($("#g-crear").textContent.startsWith("Usar")) {
    cerrarGuion();
    $("#guion").focus();
    toast("Guion cargado. Edita las líneas antes de generar.");
  } else {
    crearGuion(false);
  }
});
$("#g-otra").addEventListener("click", () => crearGuion(true));
$("#modal-guion").addEventListener("click", (e) => {
  if (e.target.id === "modal-guion") cerrarGuion();
});
$("#gtema").addEventListener("input", () => { $("#g-error").hidden = true; });
conectarChips("#gobj", "objetivo", false);
conectarChips("#gseg", "segundos", true);

$("#btn-ejemplo").addEventListener("click", () => {
  $("#guion").value = [
    "Nadie te dice esto cuando empiezas a publicar. No necesitas más equipo, necesitas publicar más.",
    "Durante seis meses compré micrófonos y cursos. Cero vistas. El día que empecé a subir tres videos por semana, llegaron las primeras mil visitas.",
    "Si estás esperando el momento perfecto, ese momento no existe. Empieza con lo que tienes hoy.",
  ].join("\n");
  actualizarContador();
  $("#guion").focus();
});

document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && $("#modal-guion").hidden) {
    e.preventDefault();
    generar();
  }
  if (e.key === "Escape") {
    if (estado.grabando) cancelarGrabacion();
    else if (!$("#modal-guion").hidden) cerrarGuion();
  }
});

// --------------------------------------------------------------- inicio

cargarAjustes();
cargarEstado();
cargarBiblioteca();
refrescarCola();
actualizarContador();

// Al volver a la pestaña, recupera trabajos encolados desde otro lado.
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refrescarCola();
});

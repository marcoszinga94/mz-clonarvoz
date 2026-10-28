// ClonarVoz — interfaz local. Sin dependencias, sin build.

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

const fmt = (s) => {
  s = Math.max(0, Math.round(s));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};
const bonito = (n) =>
  String(n).replace(/\.[^.]+$/, "").replace(/-\d+$/, "").replace(/[-_]+/g, " ").trim();

const desglosarIdioma = (v) => {
  if (v === "es-AR") return { lang: "es", variante: "argentina" };
  if (v === "es-419") return { lang: "es", variante: "latam" };
  if (v === "es-ES") return { lang: "es", variante: "espana" };
  return { lang: v, variante: "neutro" };
};

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

const estado = { refs: [], motor: "cargando", job: null, timer: null, polling: null, grabando: null };

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
    estado.packs = e.packs || {};
    pintarIdiomas(e.idiomas);
    pintarPack();
  } catch (_) {
    pintarMotor({ motor: "error", error: "no responde el servidor" });
  }
  clearTimeout(cargarEstado._t);
  cargarEstado._t = setTimeout(cargarEstado, estado.motor === "listo" ? 15000 : 2000);
}

function pintarMotor(e) {
  const dot = $("#dot");
  const txt = $("#estado-txt");
  dot.className = "dot " + (e.motor === "listo" ? "listo" : e.motor === "error" ? "error" : "cargando");
  if (e.motor === "listo") txt.textContent = "Motor listo";
  else if (e.motor === "error") txt.textContent = "Motor con error";
  else txt.textContent = "Cargando modelo";
  $("#btn-generar").disabled = e.motor !== "listo";
  $("#btn-generar").title = e.motor === "listo" ? "" : "El modelo todavía se está cargando";
}

function pintarRefs(refs) {
  const sel = $("#select-voz");
  const antes = sel.value;
  estado.refs = refs;
  sel.innerHTML = "";
  if (!refs.length) {
    sel.append(new Option("Sin referencia (voz por defecto)", ""));
  } else {
    refs.forEach((r) => {
      const sello = r.mtime ? ` · ${hora(r.mtime)}` : "";
      sel.append(new Option(`${bonito(r.nombre)} · ${fmt(r.dur)}${sello}`, r.nombre));
    });
    const elegido = refs.find((r) => r.nombre === antes) || refs[0];
    sel.value = elegido.nombre;
  }
  pintarRefAudio();
}

function pintarRefAudio() {
  const nombre = $("#select-voz").value;
  const ref = estado.refs.find((r) => r.nombre === nombre);
  const audio = $("#ref-audio");
  if (!ref) {
    audio.hidden = true;
    $("#ref-dur").textContent = "";
    return;
  }
  audio.hidden = false;
  audio.src = ref.url;
  $("#ref-dur").textContent = fmt(ref.dur);
}

function pintarPack() {
  const nota = $("#pack-nota");
  const variante = desglosarIdioma($("#lang").value).variante;
  if (variante === "neutro") { nota.hidden = true; return; }
  const clave = variante === "espana" ? "espana" : "latam";
  if ((estado.packs || {})[clave]) { nota.hidden = true; return; }
  nota.textContent = `Pack ${clave} sin instalar: se usa el modelo base. Bájalo con ./voz packs ${clave}`;
  nota.hidden = false;
}

function pintarIdiomas(idiomas) {
  const sel = $("#lang");
  if (sel.options.length) return;
  Object.entries(idiomas || {}).forEach(([k, v]) => sel.append(new Option(v, k)));
  sel.value = (estado.packs || {}).latam ? "es-AR" : "es";
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

  const items = lineas.map((texto, i) => ({ nombre: tituloDe(texto, i), texto }));
  const { lang, variante } = desglosarIdioma($("#lang").value);
  const body = {
    items,
    ref: $("#select-voz").value || null,
    lang,
    variante,
    exag: parseFloat($("#exag").value),
    cfg: parseFloat($("#cfg").value),
    seed: parseInt($("#seed").value || "42", 10),
  };

  $("#btn-generar").disabled = true;
  try {
    const r = await api("/api/generar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    seguirJob(r.job, items.length);
  } catch (e) {
    $("#btn-generar").disabled = false;
    errorGuion(String(e.message));
  }
}

function prepararTrabajo(titulo, detalle) {
  $("#trabajo").hidden = false;
  $("#trabajo-titulo").textContent = titulo;
  $("#trabajo-detalle").textContent = detalle;
  $("#resultados-parciales").innerHTML = "";
  $("#barra-fill").style.width = "2%";
  $("#spin").hidden = false;

  const t0 = performance.now();
  clearInterval(estado.timer);
  estado.timer = setInterval(() => {
    $("#trabajo-tiempo").textContent = fmt((performance.now() - t0) / 1000);
  }, 500);
}

function seguirJob(jobId, nClips) {
  prepararTrabajo("Generando", "En cola");

  let vistos = 0;
  clearTimeout(estado.polling);
  const tick = async () => {
    try {
      const j = await api(`/api/job/${jobId}`);
      $("#barra-fill").style.width = `${Math.max(2, Math.round(j.progreso * 100))}%`;
      $("#trabajo-detalle").textContent = j.detalle || "";

      if (j.resultados.length > vistos) {
        const nuevos = j.resultados.slice(vistos);
        vistos = j.resultados.length;
        nuevos.forEach((r) => {
          $("#resultados-parciales").insertAdjacentHTML("beforeend", filaResultado(r));
        });
      }

      if (j.estado === "listo") {
        clearInterval(estado.timer);
        clearTimeout(estado.polling);
        $("#spin").hidden = true;
        $("#trabajo-titulo").textContent = `${nClips} clip${nClips === 1 ? "" : "s"} listo${nClips === 1 ? "" : "s"}`;
        $("#trabajo-detalle").textContent = `Generado en ${fmt(j.segundos || 0)} · −14 LUFS · 48 kHz`;
        $("#barra-fill").style.width = "100%";
        $("#btn-generar").disabled = false;
        cargarBiblioteca();
        return;
      }
      if (j.estado === "error") {
        clearInterval(estado.timer);
        clearTimeout(estado.polling);
        $("#spin").hidden = true;
        $("#trabajo-titulo").textContent = "No se pudo generar";
        $("#trabajo-detalle").textContent = j.error || "error desconocido";
        $("#btn-generar").disabled = false;
        return;
      }
      estado.polling = setTimeout(tick, 1200);
    } catch (e) {
      clearInterval(estado.timer);
      $("#spin").hidden = true;
      $("#trabajo-titulo").textContent = "Se cortó la conexión";
      $("#trabajo-detalle").textContent = String(e.message);
      $("#btn-generar").disabled = false;
    }
  };
  estado.polling = setTimeout(tick, 600);
}

function filaResultado(r) {
  return `<div class="clip">
    <div>
      <div class="clip-t">${esc(r.titulo)}</div>
      <div class="clip-m mono">${fmt(r.dur)}</div>
    </div>
    <div class="clip-acc">
      <a class="icon-btn" href="${r.mp3}" download title="Descargar MP3" aria-label="Descargar MP3">
        <svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v12m0 0 4-4m-4 4-4-4"/><path d="M4 18v1a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-1"/></svg>
      </a>
      ${r.srt ? `<a class="icon-btn" href="${r.srt}" download title="Descargar subtítulos" aria-label="Descargar subtítulos">
        <svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 15h4M13 15h4M7 11h2M11 11h6"/></svg>
      </a>` : ""}
    </div>
    <audio controls preload="none" src="${r.mp3}"></audio>
  </div>`;
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
  return `<div class="clip">
    <div>
      <div class="clip-t">${esc(c.titulo || bonito(c.nombre))}</div>
      <div class="clip-m mono">${fmt(c.dur)} · ${cuando}</div>
    </div>
    <div class="clip-acc">
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

// --------------------------------------------------------------- transcribir

async function transcribirArchivo(file) {
  if ($("#guion").value.trim() && !confirm("La transcripción reemplaza el guion actual. ¿Seguir?")) {
    return;
  }
  const datos = new FormData();
  datos.append("archivo", file, file.name);
  datos.append("lang", desglosarIdioma($("#lang").value).lang);
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

$("#select-voz").addEventListener("change", pintarRefAudio);
$("#lang").addEventListener("change", pintarPack);
$("#exag").addEventListener("input", (e) => { $("#exag-val").textContent = (+e.target.value).toFixed(2); });
$("#cfg").addEventListener("input", (e) => { $("#cfg-val").textContent = (+e.target.value).toFixed(2); });
$("#guion").addEventListener("input", actualizarContador);
$("#btn-generar").addEventListener("click", generar);
$("#lista").addEventListener("click", (e) => {
  const b = e.target.closest("[data-borrar]");
  if (b) borrar(b.dataset.borrar);
});

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

$("#btn-reset").addEventListener("click", () => {
  $("#exag").value = 0.5; $("#exag-val").textContent = "0.50";
  $("#cfg").value = 0.5; $("#cfg-val").textContent = "0.50";
  $("#seed").value = 42; $("#lang").value = "es";
});

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

cargarEstado();
cargarBiblioteca();
actualizarContador();

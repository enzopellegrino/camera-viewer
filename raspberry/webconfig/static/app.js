"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

async function api(path, opts) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  let data = {};
  try { data = await res.json(); } catch (_) {}
  return { ok: res.ok, data };
}

function toast(msg, kind) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (kind ? " toast--" + kind : "");
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.hidden = true; }, 3000);
}

// ── Tabs ──────────────────────────────────────────────────────────────────
$$(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".tab").forEach((b) => b.classList.remove("is-active"));
    $$(".panel").forEach((p) => p.classList.remove("is-active"));
    btn.classList.add("is-active");
    $("#tab-" + btn.dataset.tab).classList.add("is-active");
  });
});

// ── Status ─────────────────────────────────────────────────────────────────
async function refreshStatus() {
  const { data } = await api("/api/status");
  const el = $("#status");
  const txt = $("#status-text");
  if (data.online) {
    el.className = "status status--on";
    if (data.type === "wifi") txt.textContent = `WiFi: ${data.ssid || "?"} · ${data.ip || ""}`;
    else txt.textContent = `Ethernet · ${data.ip || ""}`;
  } else {
    el.className = "status status--off";
    txt.textContent = "Non connesso";
  }
}

// ── Network mode toggle ──────────────────────────────────────────────────────
$("#mode-eth").addEventListener("click", () => setMode("eth"));
$("#mode-wifi").addEventListener("click", () => setMode("wifi"));

function setMode(mode) {
  const eth = mode === "eth";
  $("#mode-eth").classList.toggle("is-active", eth);
  $("#mode-wifi").classList.toggle("is-active", !eth);
  $("#eth-box").hidden = !eth;
  $("#wifi-box").hidden = eth;
  api("/api/network/mode", { method: "POST", body: JSON.stringify({ mode: eth ? "dhcp" : "wifi" }) });
}

// ── WiFi ─────────────────────────────────────────────────────────────────────
$("#scan-btn").addEventListener("click", scanWifi);

async function scanWifi() {
  $("#scan-btn").textContent = "Ricerca in corso…";
  const { data } = await api("/api/wifi/scan");
  $("#scan-btn").textContent = "🔄 Cerca reti WiFi";
  const list = $("#wifi-list");
  list.innerHTML = "";
  if (!data.networks || data.networks.length === 0) {
    list.innerHTML = '<li class="empty">Nessuna rete trovata</li>';
    return;
  }
  data.networks.forEach((n) => {
    const li = document.createElement("li");
    const locked = n.security && n.security !== "open" && n.security !== "";
    li.innerHTML = `<div class="meta"><span>${escapeHtml(n.ssid)} ${n.in_use ? "✓" : ""}</span>
      <span class="sig">Segnale ${n.signal}%</span></div>
      <span class="lock">${locked ? "🔒" : "🔓"}</span>`;
    li.addEventListener("click", () => selectWifi(n));
    list.appendChild(li);
  });
}

function selectWifi(n) {
  $("#wifi-ssid").textContent = n.ssid;
  $("#wifi-pass").value = "";
  $("#wifi-connect").hidden = false;
  $("#wifi-connect").dataset.ssid = n.ssid;
  $("#wifi-pass").focus();
}

$("#wifi-cancel-btn").addEventListener("click", () => { $("#wifi-connect").hidden = true; });

$("#wifi-connect-btn").addEventListener("click", async () => {
  const ssid = $("#wifi-connect").dataset.ssid;
  const password = $("#wifi-pass").value;
  $("#wifi-connect-btn").textContent = "Connessione…";
  const { ok, data } = await api("/api/wifi/connect", {
    method: "POST", body: JSON.stringify({ ssid, password }),
  });
  $("#wifi-connect-btn").textContent = "Connetti";
  toast(data.message || (ok ? "Connesso" : "Errore"), ok ? "ok" : "err");
  if (ok) { $("#wifi-connect").hidden = true; refreshStatus(); }
});

// ── Cameras ───────────────────────────────────────────────────────────────────
async function loadCameras() {
  const { data } = await api("/api/cameras");
  const list = $("#cam-list");
  list.innerHTML = "";
  if (!data.cameras || data.cameras.length === 0) {
    list.innerHTML = '<li class="empty">Nessuna telecamera configurata</li>';
    return;
  }
  data.cameras.forEach((c) => {
    const li = document.createElement("li");
    li.innerHTML = `<div class="meta"><span>${escapeHtml(c.name)}</span>
      <span class="url">${escapeHtml(c.url)}</span></div>
      <div class="cam-actions">
        <button class="icon-btn edit">✎</button>
        <button class="icon-btn del">🗑</button>
      </div>`;
    li.querySelector(".edit").addEventListener("click", () => editCamera(c));
    li.querySelector(".del").addEventListener("click", () => deleteCamera(c));
    list.appendChild(li);
  });
}

$("#cam-add").addEventListener("click", () => openCamForm());
$("#cam-cancel").addEventListener("click", () => { $("#cam-form").hidden = true; });

function openCamForm(cam) {
  $("#cam-id").value = cam ? cam.id : "";
  $("#cam-name").value = cam ? cam.name : "";
  $("#cam-url").value = cam ? cam.url : "rtsp://";
  $("#cam-form").hidden = false;
  $("#cam-name").focus();
}

function editCamera(c) { openCamForm(c); }

async function deleteCamera(c) {
  if (!confirm(`Eliminare "${c.name}"?`)) return;
  const { ok } = await api(`/api/cameras/${c.id}`, { method: "DELETE" });
  if (ok) { toast("Telecamera eliminata", "ok"); loadCameras(); }
}

$("#cam-save").addEventListener("click", async () => {
  const payload = {
    id: $("#cam-id").value || undefined,
    name: $("#cam-name").value,
    url: $("#cam-url").value,
  };
  const { ok, data } = await api("/api/cameras", {
    method: "POST", body: JSON.stringify(payload),
  });
  if (ok) {
    toast("Telecamera salvata", "ok");
    $("#cam-form").hidden = true;
    loadCameras();
  } else {
    toast(data.message || "Errore", "err");
  }
});

// ── Wallpaper ─────────────────────────────────────────────────────────────────
async function loadWallpaper() {
  const { data } = await api("/api/wallpaper");
  if (data.custom && data.url) {
    const box = $("#wallpaper-preview-box");
    const img = $("#wallpaper-preview");
    img.src = data.url + "?t=" + Date.now();
    box.hidden = false;
  }
}

const wallpaperFile = $("#wallpaper-file");
const wallpaperApply = $("#wallpaper-apply");
const wallpaperLabel = $("#wallpaper-label");

wallpaperFile.addEventListener("change", () => {
  const f = wallpaperFile.files[0];
  if (!f) return;
  wallpaperLabel.textContent = "📷 " + f.name;
  wallpaperApply.disabled = false;
  // Anteprima locale
  const reader = new FileReader();
  reader.onload = e => {
    const img = $("#wallpaper-preview");
    img.src = e.target.result;
    $("#wallpaper-preview-box").hidden = false;
  };
  reader.readAsDataURL(f);
});

wallpaperApply.addEventListener("click", async () => {
  const f = wallpaperFile.files[0];
  if (!f) return;
  wallpaperApply.textContent = "Invio…";
  wallpaperApply.disabled = true;
  const form = new FormData();
  form.append("file", f);
  const res = await fetch("/api/wallpaper", { method: "POST", body: form });
  const data = await res.json();
  toast(data.message || (data.ok ? "Sfondo aggiornato" : "Errore"), data.ok ? "ok" : "err");
  wallpaperApply.textContent = "Applica sfondo";
  wallpaperApply.disabled = false;
  if (data.ok) loadWallpaper();
});

$("#wallpaper-reset").addEventListener("click", async () => {
  const { ok, data } = await api("/api/wallpaper", { method: "DELETE" });
  toast(data.message || (ok ? "Sfondo ripristinato" : "Errore"), ok ? "ok" : "err");
  if (ok) {
    $("#wallpaper-preview-box").hidden = true;
    wallpaperLabel.textContent = "📂 Scegli un'immagine (JPG, PNG, WEBP)";
    wallpaperFile.value = "";
    wallpaperApply.disabled = true;
  }
});

// ── Settings ──────────────────────────────────────────────────────────────────
async function loadSettings() {
  const { data } = await api("/api/settings");
  if (data.layout) $("#set-layout").value = data.layout;
  if (data.settings && data.settings.render_fps) $("#set-fps").value = String(data.settings.render_fps);
}

$("#set-save").addEventListener("click", async () => {
  const btn = $("#set-save");
  btn.textContent = "Salvataggio…";
  btn.disabled = true;

  const payload = {
    layout: $("#set-layout").value,
    render_fps: parseInt($("#set-fps").value, 10),
  };
  const { ok } = await api("/api/settings", { method: "POST", body: JSON.stringify(payload) });
  if (!ok) {
    toast("Errore nel salvataggio", "err");
    btn.textContent = "Applica — salva e aggiorna griglia";
    btn.disabled = false;
    return;
  }

  btn.textContent = "Riavvio viewer…";
  await api("/api/restart-viewer", { method: "POST" });
  toast("Griglia aggiornata — viewer riavviato", "ok");

  btn.textContent = "Applica — salva e aggiorna griglia";
  btn.disabled = false;
});

// ── VPN ───────────────────────────────────────────────────────────────────────
let vpnProto = "wireguard";
$("#vpn-proto-wg").addEventListener("click", () => setVpnProto("wireguard"));
$("#vpn-proto-ovpn").addEventListener("click", () => setVpnProto("openvpn"));

function setVpnProto(p) {
  vpnProto = p;
  const wg = p === "wireguard";
  $("#vpn-proto-wg").classList.toggle("is-active", wg);
  $("#vpn-proto-ovpn").classList.toggle("is-active", !wg);
  $("#wg-section").hidden = !wg;
  $("#ovpn-section").hidden = wg;
}

$("#vpn-mode-file").addEventListener("click", () => setVpnMode("file"));
$("#vpn-mode-manual").addEventListener("click", () => setVpnMode("manual"));

function setVpnMode(mode) {
  const file = mode === "file";
  $("#vpn-mode-file").classList.toggle("is-active", file);
  $("#vpn-mode-manual").classList.toggle("is-active", !file);
  $("#vpn-file-box").hidden = !file;
  $("#vpn-manual-box").hidden = file;
}

function fmtBytes(n) {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return n.toFixed(1) + " " + u[i];
}

function vpnRow(label, value) {
  if (!value) return "";
  return `<tr><td class="vpn-info-label">${escapeHtml(label)}</td><td class="vpn-info-value">${escapeHtml(value)}</td></tr>`;
}

async function loadVpnStatus() {
  const { data } = await api("/api/vpn");
  const st = $("#vpn-status");
  const txt = $("#vpn-status-text");
  const detail = $("#vpn-detail");
  const rows = $("#vpn-info-rows");
  const actions = $("#vpn-actions");
  const form = $("#vpn-form");

  if (data.active) {
    const proto = data.protocol === "openvpn" ? "OpenVPN" : "WireGuard";
    const transport = (data.proto || "").toUpperCase();
    const badge = transport ? ` · ${transport}` : "";
    st.className = "status status--on";
    txt.textContent = `${proto} attiva${badge}`;
    detail.hidden = false;

    if (data.protocol === "openvpn") {
      rows.innerHTML =
        vpnRow("Server", data.server) +
        vpnRow("IP tunnel", data.tun_ip) +
        vpnRow("Route camere", data.routes);
    } else {
      const hs = data.last_handshake
        ? new Date(data.last_handshake * 1000).toLocaleTimeString()
        : "in attesa…";
      rows.innerHTML =
        vpnRow("Protocollo", "WireGuard") +
        vpnRow("Endpoint", data.endpoint) +
        vpnRow("Subnet", data.allowed_ips) +
        vpnRow("Ultimo handshake", hs) +
        vpnRow("Traffico", `↓ ${fmtBytes(data.rx)} · ↑ ${fmtBytes(data.tx)}`);
    }
    actions.hidden = false;
    form.hidden = true;
  } else if (data.configured) {
    const proto = data.protocol === "openvpn" ? "OpenVPN" : "WireGuard";
    st.className = "status status--warn";
    txt.textContent = `${proto} configurata ma non attiva`;
    rows.innerHTML = vpnRow("Protocollo", data.protocol === "openvpn" ? `OpenVPN ${data.proto || ""}` : "WireGuard") +
                     vpnRow("Server", data.server);
    detail.hidden = false;
    actions.hidden = false;
    form.hidden = true;
  } else {
    st.className = "status status--off";
    txt.textContent = "VPN non configurata";
    detail.hidden = true;
    actions.hidden = true;
    form.hidden = false;
  }
}

$("#vpn-reconfigure").addEventListener("click", () => {
  $("#vpn-form").hidden = false;
  $("#vpn-form").scrollIntoView({ behavior: "smooth" });
});

function readFileText(input) {
  return new Promise((resolve) => {
    const f = input.files && input.files[0];
    if (!f) return resolve(null);
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.readAsText(f);
  });
}

$("#vpn-apply").addEventListener("click", async () => {
  const subnets = $("#vpn-subnets").value;
  if (!subnets.trim()) { toast("Indica le subnet delle camere remote", "err"); return; }
  const payload = {
    protocol: vpnProto,
    camera_subnets: subnets,
    enable_on_boot: $("#vpn-boot").checked,
  };

  if (vpnProto === "openvpn") {
    const text = await readFileText($("#ovpn-file"));
    if (!text) { toast("Seleziona un file .ovpn", "err"); return; }
    payload.conf_text = text;
    payload.username = $("#ovpn-user").value;
    payload.password = $("#ovpn-pass").value;
  } else {
    const fileMode = $("#vpn-mode-file").classList.contains("is-active");
    if (fileMode) {
      const text = await readFileText($("#vpn-file"));
      if (!text) { toast("Seleziona un file .conf", "err"); return; }
      payload.mode = "file";
      payload.conf_text = text;
    } else {
      payload.mode = "manual";
      payload.private_key = $("#vpn-private-key").value;
      payload.address = $("#vpn-address").value;
      payload.peer_public_key = $("#vpn-public-key").value;
      payload.preshared_key = $("#vpn-psk").value;
      payload.endpoint = $("#vpn-endpoint").value;
    }
  }

  $("#vpn-apply").textContent = "Attivazione…";
  const { ok, data } = await api("/api/vpn", { method: "POST", body: JSON.stringify(payload) });
  $("#vpn-apply").textContent = "Attiva VPN";
  toast(data.message || (ok ? "VPN attivata" : "Errore"), ok ? "ok" : "err");
  if (ok) loadVpnStatus();
});

$("#vpn-disable").addEventListener("click", async () => {
  const { ok, data } = await api("/api/vpn/disable", { method: "POST" });
  toast(data.message || (ok ? "VPN disattivata" : "Errore"), ok ? "ok" : "err");
  loadVpnStatus();
});

$("#vpn-remove").addEventListener("click", async () => {
  if (!confirm("Rimuovere la configurazione VPN?")) return;
  const { ok, data } = await api("/api/vpn", { method: "DELETE" });
  toast(data.message || (ok ? "VPN rimossa" : "Errore"), ok ? "ok" : "err");
  loadVpnStatus();
});

// ── Apply / start viewer ──────────────────────────────────────────────────────
$("#apply-btn").addEventListener("click", async () => {
  if (!confirm("Avviare il viewer? Il dispositivo si riavvierà e mostrerà le telecamere sul monitor.")) return;
  const { ok, data } = await api("/api/apply", { method: "POST" });
  if (ok) {
    toast(data.message || "Riavvio in corso…", "ok");
    document.body.innerHTML =
      '<div style="display:flex;align-items:center;justify-content:center;height:100vh;text-align:center;padding:24px">' +
      '<div><h2>Riavvio in corso…</h2><p style="color:#9a9a9a">Il dispositivo si sta avviando con le telecamere configurate.<br>' +
      'Puoi chiudere questa pagina.</p></div></div>';
  } else {
    toast(data.message || "Errore", "err");
  }
});

// ── Utils ──────────────────────────────────────────────────────────────────────
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// ── Init ─────────────────────────────────────────────────────────────────────
refreshStatus();
loadCameras();
loadSettings();
loadVpnStatus();
loadWallpaper();
setInterval(refreshStatus, 8000);

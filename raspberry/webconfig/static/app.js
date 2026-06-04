/* Camera Viewer — Portal app.js v2.0 */
'use strict';

// ── Helpers ───────────────────────────────────────────────────────────────
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

let _currentUser = null;

async function api(url, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  try {
    const res = await fetch(url, { ...opts, headers });
    if (res.status === 401) { window.location.href = '/login'; return { ok: false, data: {} }; }
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, data };
  } catch (e) {
    return { ok: false, data: { message: 'Errore di rete' } };
  }
}

let _toastTimer;
function toast(msg, type = 'ok') {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast ' + type;
  t.hidden = false;
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { t.hidden = true; }, 3200);
}

// ── Navigation ────────────────────────────────────────────────────────────
function switchTab(name) {
  $$('.nav-item').forEach(el => el.classList.toggle('active', el.dataset.tab === name));
  $$('.bnav-item').forEach(el => el.classList.toggle('active', el.dataset.tab === name));
  $$('.panel').forEach(el => el.classList.toggle('active', el.id === 'tab-' + name));
  // Persist tab across page refreshes
  try { localStorage.setItem('cv-tab', name); } catch(e) {}
  // Close sidebar on mobile
  if (window.innerWidth <= 768) $('#sidebar').classList.remove('open');
}

$$('[data-tab]').forEach(el => {
  el.addEventListener('click', () => switchTab(el.dataset.tab));
});

$('#menu-btn').addEventListener('click', () => {
  $('#sidebar').classList.toggle('open');
});

document.addEventListener('click', e => {
  const sidebar = $('#sidebar');
  if (window.innerWidth <= 768 && sidebar.classList.contains('open')
      && !sidebar.contains(e.target) && !$('#menu-btn').contains(e.target)) {
    sidebar.classList.remove('open');
  }
});

// ── Role visibility ───────────────────────────────────────────────────────
function applyRole(role) {
  const isAdmin = role === 'admin';
  $$('.admin-only').forEach(el => el.classList.toggle('hidden', !isAdmin));
}

// ── Auth ──────────────────────────────────────────────────────────────────
async function initAuth() {
  const { ok, data } = await api('/api/auth/me');
  if (!ok) { window.location.href = '/login'; return false; }
  _currentUser = data;
  $('#user-name').textContent = data.username;
  $('#user-avatar').textContent = data.username[0].toUpperCase();
  $('#user-role-label').textContent = data.role === 'admin' ? 'Amministratore' : 'Operatore';
  applyRole(data.role);
  return true;
}

$('#logout-btn').addEventListener('click', async () => {
  await api('/api/auth/logout', { method: 'POST' });
  window.location.href = '/login';
});

// ── Site name & status ────────────────────────────────────────────────────
async function loadSiteName() {
  const { data } = await api('/api/site-name');
  const name = data.name || 'Camera Viewer';
  $('#brand-name').textContent = name;
  $('#site-title').textContent = name;
  document.title = name;
  const inp = $('#site-name-input');
  if (inp) inp.value = name;
}

$('#site-name-save')?.addEventListener('click', async () => {
  const { ok, data } = await api('/api/site-name', {
    method: 'POST', body: JSON.stringify({ name: $('#site-name-input').value })
  });
  if (ok) { toast('Nome aggiornato', 'ok'); loadSiteName(); }
  else toast(data.message || 'Errore', 'err');
});

async function loadStatus() {
  const { ok, data } = await api('/api/status');
  const dot = $('#status-dot'), txt = $('#status-text'), ip = $('#ip-badge');
  if (ok && data.online) {
    dot.className = 'status-dot online';
    txt.textContent = data.type === 'wifi' ? `WiFi: ${data.ssid}` : 'Ethernet';
    ip.textContent = data.ip || '';
  } else {
    dot.className = 'status-dot offline';
    txt.textContent = 'Non connesso';
    ip.textContent = '';
  }
}

// ── Cameras ───────────────────────────────────────────────────────────────
let _cameras = [];
let _editingCamId = null;

async function loadCameras() {
  const { data } = await api('/api/cameras');
  _cameras = data.cameras || [];
  renderCameras();
}

function renderCameras() {
  const list = $('#cam-list');
  if (!_cameras.length) {
    list.innerHTML = '<p class="text-muted" style="padding:12px 0">Nessuna telecamera configurata.</p>';
    return;
  }
  const isAdmin = _currentUser?.role === 'admin';
  list.innerHTML = _cameras.map(c => `
    <div class="cam-card" data-id="${c.id}">
      <div class="cam-card-info">
        <div class="cam-card-name">${esc(c.name)}</div>
        <div class="cam-card-url">${esc(c.url)}</div>
      </div>
      <div class="cam-card-actions">
        <button class="btn btn-sm" onclick="zoomCam('${c.id}')" title="Mostra sul TV">🔍</button>
        ${isAdmin ? `
          <button class="btn-icon" onclick="editCam('${c.id}')" title="Modifica">
            <svg viewBox="0 0 24 24"><path d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
          </button>
          <button class="btn-icon danger" onclick="deleteCam('${c.id}')" title="Elimina">
            <svg viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a1 1 0 011-1h4a1 1 0 011 1v2"/></svg>
          </button>` : ''}
      </div>
    </div>`).join('');
}

function esc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

window.editCam = id => {
  _editingCamId = id;
  const c = _cameras.find(x => x.id === id);
  if (!c) return;
  $('#cam-form-title').textContent = 'Modifica telecamera';
  $('#cam-name').value = c.name;
  $('#cam-url').value = c.url;
  $('#cam-pass').value = c.passphrase || '';
  $('#cam-pass-row').classList.toggle('hidden', !c.url.toLowerCase().startsWith('srt://'));
  $('#cam-form').classList.remove('hidden');
  $('#cam-name').focus();
};

window.deleteCam = async id => {
  const c = _cameras.find(x => x.id === id);
  if (!c || !confirm(`Eliminare "${c.name}"?`)) return;
  const { ok, data } = await api(`/api/cameras/${id}`, { method: 'DELETE' });
  if (ok) { toast('Telecamera eliminata', 'ok'); loadCameras(); loadViews(); }
  else toast(data.message || 'Errore', 'err');
};

window.zoomCam = async id => {
  await api('/api/viewer/zoom', { method: 'POST', body: JSON.stringify({ camera_id: id }) });
  toast('Vista inviata alla TV', 'ok');
};

$('#add-cam-btn')?.addEventListener('click', () => {
  _editingCamId = null;
  $('#cam-form-title').textContent = 'Nuova telecamera';
  $('#cam-name').value = ''; $('#cam-url').value = ''; $('#cam-pass').value = '';
  $('#cam-pass-row').classList.add('hidden');
  $('#cam-form').classList.remove('hidden');
  $('#cam-name').focus();
});

$('#cam-url')?.addEventListener('input', () => {
  $('#cam-pass-row').classList.toggle('hidden', !$('#cam-url').value.toLowerCase().startsWith('srt://'));
});

$('#cam-save')?.addEventListener('click', async () => {
  const body = {
    id: _editingCamId || undefined,
    name: $('#cam-name').value.trim(),
    url: $('#cam-url').value.trim(),
    passphrase: $('#cam-pass').value.trim() || undefined,
  };
  if (!body.name || !body.url) { toast('Nome e URL obbligatori', 'err'); return; }
  const { ok, data } = await api('/api/cameras', { method: 'POST', body: JSON.stringify(body) });
  if (ok) {
    toast(_editingCamId ? 'Telecamera aggiornata' : 'Telecamera aggiunta', 'ok');
    $('#cam-form').classList.add('hidden');
    loadCameras(); loadViews();
  } else toast(data.message || 'Errore', 'err');
});

$('#cam-cancel')?.addEventListener('click', () => $('#cam-form').classList.add('hidden'));

// ── Views / Screens ───────────────────────────────────────────────────────
let _screens = [], _activeScreenId = '', _editingScreenId = null;

async function loadViews() {
  const { data } = await api('/api/screens');
  _screens = data.screens || [];
  _activeScreenId = data.active_screen_id || '';
  renderViews();
}

function layoutPreviewSvg(layout, size = 36) {
  const map = { 'auto':[2,2],'1x1':[1,1],'1x2':[1,2],'2x1':[2,1],
    '2x2':[2,2],'3x2':[3,2],'2x3':[2,3],'3x3':[3,3],'4x4':[4,4] };
  const [rows, cols] = map[layout] || [2,2];
  const gap = 2, cw = (size - gap*(cols-1))/cols, ch = (size - gap*(rows-1))/rows;
  let rects = '';
  for (let r = 0; r < rows; r++)
    for (let c = 0; c < cols; c++) {
      const x = (c*(cw+gap)).toFixed(1), y = (r*(ch+gap)).toFixed(1);
      rects += `<rect x="${x}" y="${y}" width="${cw.toFixed(1)}" height="${ch.toFixed(1)}" rx="1"
        fill="var(--accent-dim)" stroke="var(--accent)" stroke-width="0.5"/>`;
    }
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">${rects}</svg>`;
}

function renderViews() {
  const list = $('#views-list');
  if (!_screens.length) {
    list.innerHTML = '<p class="text-muted" style="padding:12px 0">Nessuna vista configurata.</p>';
    return;
  }
  const isAdmin = _currentUser?.role === 'admin';
  list.innerHTML = _screens.map(s => {
    const isActive = s.id === _activeScreenId;
    const camCount = (s.cameras || []).length;
    return `
    <div class="view-card ${isActive ? 'active-view' : ''}" data-id="${s.id}">
      <div class="view-card-top">
        ${layoutPreviewSvg(s.layout)}
        <div class="view-info">
          <div class="view-name">${esc(s.name)}</div>
          <div class="view-meta">${s.layout} · ${camCount} cam</div>
          ${isActive ? '<span class="active-badge">▶ Attiva</span>' : ''}
        </div>
      </div>
      <div class="view-actions">
        <button class="btn btn-primary btn-sm" onclick="activateView('${s.id}')">▶ Mostra sul TV</button>
        ${isAdmin ? `
        <button class="btn-icon" onclick="editView('${s.id}')" title="Modifica">
          <svg viewBox="0 0 24 24"><path d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
        </button>
        <button class="btn-icon danger" onclick="deleteView('${s.id}')" title="Elimina">
          <svg viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a1 1 0 011-1h4a1 1 0 011 1v2"/></svg>
        </button>` : ''}
      </div>
    </div>`;
  }).join('');
}

window.activateView = async id => {
  const { ok, data } = await api(`/api/screens/${id}/activate`, { method: 'POST' });
  if (ok) { _activeScreenId = id; renderViews(); toast('Vista inviata alla TV', 'ok'); }
  else toast(data.message || 'Errore', 'err');
};

window.editView = id => {
  _editingScreenId = id;
  const s = _screens.find(x => x.id === id);
  if (!s) return;
  $('#view-form-title').textContent = 'Modifica vista';
  $('#view-name').value = s.name;
  $('#view-layout').value = s.layout;
  renderCamPicker(s.cameras || []);
  $('#view-form').classList.remove('hidden');
  $('#view-name').focus();
};

window.deleteView = async id => {
  const s = _screens.find(x => x.id === id);
  if (!s || !confirm(`Eliminare la vista "${s.name}"?`)) return;
  const { ok, data } = await api(`/api/screens/${id}`, { method: 'DELETE' });
  if (ok) { toast('Vista eliminata', 'ok'); loadViews(); }
  else toast(data.message || 'Errore', 'err');
};

$('#add-view-btn')?.addEventListener('click', () => {
  _editingScreenId = null;
  $('#view-form-title').textContent = 'Nuova vista';
  $('#view-name').value = '';
  $('#view-layout').value = 'auto';
  renderCamPicker([]);
  $('#view-form').classList.remove('hidden');
  $('#view-name').focus();
});

function renderCamPicker(selected) {
  const box = $('#view-cam-picker');
  if (!_cameras.length) { box.innerHTML = '<p class="text-muted">Aggiungi prima le telecamere.</p>'; return; }
  box.innerHTML = _cameras.map(c => {
    const checked = selected.includes(c.id);
    return `
    <label class="cam-pick-item ${checked ? 'selected' : ''}" onclick="toggleCamPick(this,'${c.id}')">
      <input type="checkbox" ${checked ? 'checked' : ''} data-cam-id="${c.id}" onclick="event.stopPropagation()"/>
      <span>${esc(c.name)}</span>
    </label>`;
  }).join('');
}

window.toggleCamPick = (el, id) => {
  const cb = el.querySelector('input');
  cb.checked = !cb.checked;
  el.classList.toggle('selected', cb.checked);
};

$('#view-save')?.addEventListener('click', async () => {
  const name = $('#view-name').value.trim();
  if (!name) { toast('Il nome è obbligatorio', 'err'); return; }
  const cameras = $$('#view-cam-picker input:checked').map(cb => cb.dataset.camId);
  const body = { id: _editingScreenId || undefined, name, layout: $('#view-layout').value, cameras };
  const url = _editingScreenId ? `/api/screens/${_editingScreenId}` : '/api/screens';
  const method = _editingScreenId ? 'PUT' : 'POST';
  const { ok, data } = await api(url, { method, body: JSON.stringify(body) });
  if (ok) {
    toast(_editingScreenId ? 'Vista aggiornata' : 'Vista creata', 'ok');
    $('#view-form').classList.add('hidden');
    loadViews();
  } else toast(data.message || 'Errore', 'err');
});

$('#view-cancel')?.addEventListener('click', () => $('#view-form').classList.add('hidden'));

// ── Settings ──────────────────────────────────────────────────────────────
async function loadSettings() {
  const { data } = await api('/api/settings');
  if (data.layout) $('#set-layout').value = data.layout;
  if (data.settings?.render_fps) $('#set-fps').value = String(data.settings.render_fps);
}

$('#set-save')?.addEventListener('click', async () => {
  const btn = $('#set-save');
  btn.disabled = true; btn.textContent = 'Salvataggio…';
  const { ok } = await api('/api/settings', {
    method: 'POST',
    body: JSON.stringify({ layout: $('#set-layout').value, render_fps: parseInt($('#set-fps').value) })
  });
  toast(ok ? 'Impostazioni salvate' : 'Errore', ok ? 'ok' : 'err');
  btn.disabled = false; btn.textContent = 'Salva impostazioni';
});

// ── Restart viewer ────────────────────────────────────────────────────────
$('#restart-viewer-btn')?.addEventListener('click', async () => {
  const btn = $('#restart-viewer-btn');
  btn.disabled = true; btn.textContent = 'Riavvio…';
  const { ok, data } = await api('/api/restart-viewer', { method: 'POST' });
  toast(data.message || (ok ? 'Viewer riavviato' : 'Errore'), ok ? 'ok' : 'err');
  btn.disabled = false; btn.textContent = '🔄 Riavvia viewer';
});

// ── Placeholder ───────────────────────────────────────────────────────────
async function loadPlaceholder() {
  const { data } = await api('/api/placeholder');
  if (data?.custom && data.url) {
    $('#placeholder-preview').src = data.url + '?t=' + Date.now();
    $('#placeholder-preview-box').hidden = false;
  }
}

const phFile = $('#placeholder-file');
phFile?.addEventListener('change', () => {
  const f = phFile.files[0]; if (!f) return;
  $('#placeholder-label').textContent = '🖼 ' + f.name;
  $('#placeholder-apply').disabled = false;
  const reader = new FileReader();
  reader.onload = e => { $('#placeholder-preview').src = e.target.result; $('#placeholder-preview-box').hidden = false; };
  reader.readAsDataURL(f);
});

$('#placeholder-apply')?.addEventListener('click', async () => {
  const f = phFile?.files[0]; if (!f) return;
  const btn = $('#placeholder-apply');
  btn.disabled = true; btn.textContent = 'Invio…';
  const form = new FormData(); form.append('file', f);
  const res = await fetch('/api/placeholder', { method: 'POST', body: form });
  const data = await res.json();
  toast(data.message || (data.ok ? 'Logo aggiornato' : 'Errore'), data.ok ? 'ok' : 'err');
  btn.textContent = 'Applica logo'; btn.disabled = false;
  if (data.ok) loadPlaceholder();
});

$('#placeholder-reset')?.addEventListener('click', async () => {
  const { ok, data } = await api('/api/placeholder', { method: 'DELETE' });
  toast(data.message || (ok ? 'Logo rimosso' : 'Errore'), ok ? 'ok' : 'err');
  if (ok) {
    $('#placeholder-preview-box').hidden = true;
    $('#placeholder-label').textContent = '📂 Scegli un\'immagine (JPG, PNG, WEBP)';
    if (phFile) phFile.value = '';
    $('#placeholder-apply').disabled = true;
  }
});

// ── Wallpaper ─────────────────────────────────────────────────────────────
async function loadWallpaper() {
  const { data } = await api('/api/wallpaper');
  if (data?.custom && data.url) {
    $('#wallpaper-preview').src = data.url + '?t=' + Date.now();
    $('#wallpaper-preview-box').hidden = false;
  }
}

const wpFile = $('#wallpaper-file');
wpFile?.addEventListener('change', () => {
  const f = wpFile.files[0]; if (!f) return;
  $('#wallpaper-label').textContent = '📷 ' + f.name;
  $('#wallpaper-apply').disabled = false;
  const reader = new FileReader();
  reader.onload = e => { $('#wallpaper-preview').src = e.target.result; $('#wallpaper-preview-box').hidden = false; };
  reader.readAsDataURL(f);
});

$('#wallpaper-apply')?.addEventListener('click', async () => {
  const f = wpFile?.files[0]; if (!f) return;
  const btn = $('#wallpaper-apply');
  btn.disabled = true; btn.textContent = 'Invio…';
  const form = new FormData(); form.append('file', f);
  const res = await fetch('/api/wallpaper', { method: 'POST', body: form });
  const data = await res.json();
  toast(data.message || (data.ok ? 'Sfondo aggiornato' : 'Errore'), data.ok ? 'ok' : 'err');
  btn.textContent = 'Applica sfondo'; btn.disabled = false;
  if (data.ok) loadWallpaper();
});

$('#wallpaper-reset')?.addEventListener('click', async () => {
  const { ok, data } = await api('/api/wallpaper', { method: 'DELETE' });
  toast(data.message || (ok ? 'Sfondo ripristinato' : 'Errore'), ok ? 'ok' : 'err');
  if (ok) {
    $('#wallpaper-preview-box').hidden = true;
    $('#wallpaper-label').textContent = '📂 Scegli un\'immagine (JPG, PNG, WEBP)';
    if (wpFile) wpFile.value = '';
    $('#wallpaper-apply').disabled = true;
  }
});

// ── VPN Profiles ──────────────────────────────────────────────────────────
let _vpnProfiles = [], _vpnActiveId = null, _editingVpnId = null;

async function loadVpnStatus() {
  const [statusRes, profilesRes] = await Promise.all([
    api('/api/vpn'),
    api('/api/vpn/profiles'),
  ]);
  const st = statusRes.data;
  _vpnProfiles = profilesRes.data?.profiles || [];
  _vpnActiveId = profilesRes.data?.active_id || null;

  const ind = $('#vpn-status-indicator'), txt = $('#vpn-status-text'), sub = $('#vpn-status-sub');
  if (st.active) {
    ind.className = 'status-indicator active'; ind.textContent = '🔒';
    // Show profile name if we know which one is active
    const activeProfile = _vpnProfiles.find(p => p.id === _vpnActiveId);
    const protoLabel = st.protocol === 'openvpn' ? 'OpenVPN' : 'WireGuard';
    txt.textContent = activeProfile
      ? `${activeProfile.name} — ${protoLabel} attivo`
      : `${protoLabel} attivo`;
    sub.textContent = st.ip || '';
  } else {
    ind.className = 'status-indicator'; ind.textContent = '🔓';
    txt.textContent = 'Nessun tunnel attivo';
    sub.textContent = '';
  }
  renderVpnProfiles();
}

function renderVpnProfiles() {
  const list = $('#vpn-profiles-list');
  if (!list) return;
  if (!_vpnProfiles.length) {
    list.innerHTML = `<div class="card text-muted" style="text-align:center;padding:24px">
      <div style="font-size:2rem;margin-bottom:8px">🔓</div>
      <p>Nessun profilo VPN configurato.</p>
      <p style="margin-top:6px;font-size:.8rem">Aggiungi un profilo con il pulsante "+ Nuovo profilo".</p>
    </div>`;
    return;
  }
  const isAdmin = _currentUser?.role === 'admin';
  list.innerHTML = _vpnProfiles.map(p => {
    const isActive = p.id === _vpnActiveId;
    const subnets = (p.camera_subnets || []).map(s =>
      `<span class="subnet-pill">${esc(s)}</span>`).join(' ');
    const protoBadge = `<span class="proto-badge">${p.protocol === 'openvpn' ? 'OpenVPN' : 'WireGuard'}</span>`;
    const autoTag = p.auto_connect ? `<span class="proto-badge" style="background:rgba(245,166,35,.1);color:var(--warning);border-color:rgba(245,166,35,.25)">🔄 auto</span>` : '';

    return `
    <div class="vpn-profile-card ${isActive ? 'is-active' : ''}">
      <div class="vpn-profile-head">
        <div class="vpn-profile-icon">${isActive ? '🔒' : '🔓'}</div>
        <div class="vpn-profile-meta">
          <div class="vpn-profile-name">${esc(p.name)}</div>
          <div class="vpn-profile-proto">${protoBadge}${autoTag}${subnets}</div>
        </div>
      </div>
      <div class="vpn-profile-actions">
        ${isActive
          ? `<span class="active-badge-vpn">Attivo</span>
             ${isAdmin ? `<button class="btn btn-sm btn-danger" onclick="deactivateVpn('${p.id}')">Disattiva</button>` : ''}`
          : `${isAdmin ? `<button class="btn btn-primary btn-sm" onclick="activateVpn('${p.id}')">▶ Attiva</button>` : ''}`}
        ${isAdmin ? `
        <button class="btn-icon" onclick="editVpnProfile('${p.id}')" title="Modifica">
          <svg viewBox="0 0 24 24"><path d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
        </button>
        <button class="btn-icon danger" onclick="deleteVpnProfile('${p.id}','${esc(p.name)}')" title="Elimina">
          <svg viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a1 1 0 011-1h4a1 1 0 011 1v2"/></svg>
        </button>` : ''}
      </div>
    </div>`;
  }).join('');
}

window.activateVpn = async id => {
  const p = _vpnProfiles.find(x => x.id === id);
  const profileName = p?.name || 'VPN';

  // Mostra subito lo stato "connessione in corso"
  const ind = $('#vpn-status-indicator'), txt = $('#vpn-status-text'), sub = $('#vpn-status-sub');
  if (ind) { ind.className = 'status-indicator connecting'; ind.textContent = '⏳'; }
  if (txt) txt.textContent = `${profileName} — Connessione in corso…`;
  if (sub) sub.textContent = '';

  const { ok, data } = await api(`/api/vpn/profiles/${id}/activate`, { method: 'POST' });
  if (!ok) {
    toast(data.message || 'Errore attivazione VPN', 'err');
    await loadVpnStatus();
    return;
  }

  // Polling ogni 2s finché il tunnel è attivo (max 20 tentativi = 40s)
  toast(`${profileName}: connessione in corso…`, 'ok');
  let connected = false;
  for (let i = 0; i < 20; i++) {
    await new Promise(r => setTimeout(r, 2000));
    const { data: st } = await api('/api/vpn');
    if (st.active) { connected = true; break; }
    if (txt) txt.textContent = `${profileName} — Connessione in corso… (${(i+1)*2}s)`;
  }

  if (connected) {
    toast(`${profileName} connesso!`, 'ok');
  } else {
    toast('Timeout: VPN non connessa. Controlla le credenziali.', 'err');
  }
  await loadVpnStatus();
};

window.deactivateVpn = async id => {
  const { ok, data } = await api(`/api/vpn/profiles/${id}/deactivate`, { method: 'POST' });
  toast(data.message || (ok ? 'VPN disattivata' : 'Errore'), ok ? 'ok' : 'err');
  await loadVpnStatus();
};

window.editVpnProfile = id => {
  _editingVpnId = id;
  const p = _vpnProfiles.find(x => x.id === id);
  if (!p) return;
  $('#vpn-form-title').textContent = 'Modifica profilo';
  $('#vpn-name').value = p.name;
  $('#vpn-autoconnect').checked = !!p.auto_connect;
  $('#vpn-subnets').value = (p.camera_subnets || []).join('\n');
  // Set protocol
  const proto = p.protocol || 'openvpn';
  $$('#vpn-proto-seg .seg-btn').forEach(b => b.classList.toggle('active', b.dataset.val === proto));
  $('#ovpn-section').hidden = proto !== 'openvpn';
  $('#wg-section').hidden = proto !== 'wireguard';
  $('#ovpn-user').value = p.username || '';
  $('#ovpn-pass').value = '';  // don't prefill password
  $('#ovpn-label').textContent = p.conf_text ? '📄 Config salvata (carica per sostituire)' : '📂 Scegli il file .ovpn';
  $('#vpn-profile-form').classList.remove('hidden');
  $('#vpn-name').focus();
};

window.deleteVpnProfile = async (id, name) => {
  if (!confirm(`Eliminare il profilo "${name}"?`)) return;
  const { ok, data } = await api(`/api/vpn/profiles/${id}`, { method: 'DELETE' });
  toast(data.message || (ok ? 'Profilo eliminato' : 'Errore'), ok ? 'ok' : 'err');
  if (ok) await loadVpnStatus();
};

$('#add-vpn-btn')?.addEventListener('click', () => {
  _editingVpnId = null;
  $('#vpn-form-title').textContent = 'Nuovo profilo VPN';
  $('#vpn-name').value = '';
  $('#ovpn-user').value = ''; $('#ovpn-pass').value = '';
  $('#vpn-subnets').value = ''; $('#vpn-autoconnect').checked = true;
  $('#ovpn-label').textContent = '📂 Scegli o trascina il file .ovpn';
  $('#wg-label').textContent = '📂 Scegli il file WireGuard .conf';
  $$('#vpn-proto-seg .seg-btn').forEach((b,i) => b.classList.toggle('active', i === 0));
  $('#ovpn-section').hidden = false; $('#wg-section').hidden = true;
  $('#vpn-profile-form').classList.remove('hidden');
  $('#vpn-name').focus();
});

$('#vpn-profile-cancel')?.addEventListener('click', () => {
  $('#vpn-profile-form').classList.add('hidden');
});

// Proto seg
$$('#vpn-proto-seg .seg-btn').forEach(b => b.addEventListener('click', () => {
  $$('#vpn-proto-seg .seg-btn').forEach(x => x.classList.remove('active'));
  b.classList.add('active');
  $('#ovpn-section').hidden = b.dataset.val !== 'openvpn';
  $('#wg-section').hidden = b.dataset.val !== 'wireguard';
}));

// WG mode seg
$$('#wg-mode-seg .seg-btn').forEach(b => b.addEventListener('click', () => {
  $$('#wg-mode-seg .seg-btn').forEach(x => x.classList.remove('active'));
  b.classList.add('active');
  $('#wg-file-box').hidden = b.dataset.val !== 'file';
  $('#wg-manual-box').hidden = b.dataset.val !== 'manual';
}));

$('#ovpn-drop')?.addEventListener('click', () => $('#ovpn-file').click());
$('#ovpn-file')?.addEventListener('change', () => {
  const f = $('#ovpn-file').files[0];
  if (f) $('#ovpn-label').textContent = '📄 ' + f.name;
});
$('#wg-drop')?.addEventListener('click', () => $('#wg-file').click());
$('#wg-file')?.addEventListener('change', () => {
  const f = $('#wg-file').files[0];
  if (f) $('#wg-label').textContent = '📄 ' + f.name;
});

$('#vpn-profile-save')?.addEventListener('click', async () => {
  const name = $('#vpn-name').value.trim();
  if (!name) { toast('Il nome è obbligatorio', 'err'); return; }

  const btn = $('#vpn-profile-save');
  btn.disabled = true; btn.textContent = 'Salvataggio…';

  const proto = ($('#vpn-proto-seg .seg-btn.active') || {}).dataset?.val || 'openvpn';
  const subnets = $('#vpn-subnets').value.split(/[\n,;]+/).map(s => s.trim()).filter(Boolean);

  const body = {
    id: _editingVpnId || undefined,
    name, protocol: proto,
    camera_subnets: subnets,
    auto_connect: $('#vpn-autoconnect').checked,
    username: $('#ovpn-user').value,
    password: $('#ovpn-pass').value || '••••',  // preserve if not changed
  };

  if (proto === 'openvpn') {
    const f = $('#ovpn-file').files[0];
    if (f) body.conf_text = await f.text();
  } else {
    const mode = ($('#wg-mode-seg .seg-btn.active') || {}).dataset?.val || 'file';
    if (mode === 'file') {
      const f = $('#wg-file').files[0];
      if (f) { body.mode = 'file'; body.conf_text = await f.text(); }
    } else {
      body.mode = 'manual';
      body.private_key = $('#wg-private-key').value || '••••';
      body.address = $('#wg-address').value;
      body.peer_public_key = $('#wg-peer-pub').value;
      body.preshared_key = $('#wg-psk').value || '••••';
      body.endpoint = $('#wg-endpoint').value;
    }
  }

  const url = _editingVpnId ? `/api/vpn/profiles/${_editingVpnId}` : '/api/vpn/profiles';
  const method = _editingVpnId ? 'PUT' : 'POST';
  const { ok, data } = await api(url, { method, body: JSON.stringify(body) });
  toast(data.message || (ok ? 'Profilo salvato' : 'Errore'), ok ? 'ok' : 'err');
  btn.disabled = false; btn.textContent = 'Salva profilo';
  if (ok) {
    $('#vpn-profile-form').classList.add('hidden');
    await loadVpnStatus();
  }
});

// ── Users ─────────────────────────────────────────────────────────────────
let _users = [];

async function loadUsers() {
  if (_currentUser?.role !== 'admin') return;
  const { data } = await api('/api/users');
  _users = data.users || [];
  renderUsers();
}

function renderUsers() {
  const list = $('#users-list');
  if (!list) return;
  if (!_users.length) { list.innerHTML = '<p class="text-muted">Nessun utente.</p>'; return; }
  list.innerHTML = _users.map(u => `
    <div class="user-row">
      <div class="user-avatar" style="width:32px;height:32px;border-radius:50%;background:var(--accent);
        color:#fff;font-size:.85rem;font-weight:700;display:flex;align-items:center;justify-content:center;flex-shrink:0">
        ${u.username[0].toUpperCase()}</div>
      <div class="user-row-info">
        <div class="user-row-name">${esc(u.username)}</div>
        <span class="role-badge ${u.role === 'operator' ? 'operator' : ''}">
          ${u.role === 'admin' ? 'Amministratore' : 'Operatore'}
        </span>
      </div>
      <div class="cam-card-actions">
        ${u.id !== _currentUser?.id ? `
        <button class="btn-icon danger" onclick="deleteUser('${u.id}','${esc(u.username)}')" title="Elimina">
          <svg viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a1 1 0 011-1h4a1 1 0 011 1v2"/></svg>
        </button>` : '<span class="text-muted" style="font-size:.75rem;padding:0 8px">Tu</span>'}
      </div>
    </div>`).join('');
}

window.deleteUser = async (id, name) => {
  if (!confirm(`Eliminare l'utente "${name}"?`)) return;
  const { ok, data } = await api(`/api/users/${id}`, { method: 'DELETE' });
  toast(data.message || (ok ? 'Utente eliminato' : 'Errore'), ok ? 'ok' : 'err');
  if (ok) loadUsers();
};

$('#add-user-btn')?.addEventListener('click', () => {
  $('#user-username').value = ''; $('#user-password').value = ''; $('#user-role').value = 'operator';
  $('#user-form').classList.remove('hidden');
  $('#user-username').focus();
});

$('#user-save')?.addEventListener('click', async () => {
  const body = {
    username: $('#user-username').value.trim(),
    password: $('#user-password').value,
    role: $('#user-role').value,
  };
  if (!body.username || !body.password) { toast('Username e password obbligatori', 'err'); return; }
  const { ok, data } = await api('/api/users', { method: 'POST', body: JSON.stringify(body) });
  if (ok) { toast('Utente creato', 'ok'); $('#user-form').classList.add('hidden'); loadUsers(); }
  else toast(data.message || 'Errore', 'err');
});

$('#user-cancel')?.addEventListener('click', () => $('#user-form').classList.add('hidden'));

// Change own password
$('#own-password-save')?.addEventListener('click', async () => {
  const pw = $('#own-password').value;
  if (pw.length < 4) { toast('Password troppo corta', 'err'); return; }
  const { ok, data } = await api(`/api/users/${_currentUser.id}/password`, {
    method: 'PUT', body: JSON.stringify({ password: pw })
  });
  toast(data.message || (ok ? 'Password aggiornata' : 'Errore'), ok ? 'ok' : 'err');
  if (ok) $('#own-password').value = '';
});

// ── Configurazione IP rete ────────────────────────────────────────────────
const _netMethod = { eth: 'auto', wifi: 'auto' };

window.setNetMethod = (type, val, btn) => {
  _netMethod[type] = val;
  const seg = type === 'eth' ? '#eth-method-seg' : '#wifi-method-seg';
  $$(seg + ' .seg-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  const fields = type === 'eth' ? '#eth-static-fields' : '#wifi-static-fields';
  $(fields).classList.toggle('hidden', val === 'auto');
};

async function loadNetworkConfig() {
  const { ok, data } = await api('/api/network/config');
  if (!ok) return;
  // Ethernet
  if (data.ethernet) {
    const m = data.ethernet.method === 'manual' ? 'manual' : 'auto';
    _netMethod.eth = m;
    $$('#eth-method-seg .seg-btn').forEach(b => b.classList.toggle('active', b.dataset.val === m));
    $('#eth-static-fields').classList.toggle('hidden', m === 'auto');
    if (data.ethernet.address) $('#eth-address').value = data.ethernet.address;
    if (data.ethernet.gateway) $('#eth-gateway').value = data.ethernet.gateway;
    if (data.ethernet.dns) $('#eth-dns').value = data.ethernet.dns;
  }
  // WiFi
  if (data.wifi) {
    const m = data.wifi.method === 'manual' ? 'manual' : 'auto';
    _netMethod.wifi = m;
    $$('#wifi-method-seg .seg-btn').forEach(b => b.classList.toggle('active', b.dataset.val === m));
    $('#wifi-static-fields').classList.toggle('hidden', m === 'auto');
    if (data.wifi.address) $('#wifi-ip-address').value = data.wifi.address;
    if (data.wifi.gateway) $('#wifi-ip-gateway').value = data.wifi.gateway;
    if (data.wifi.dns) $('#wifi-ip-dns').value = data.wifi.dns;
  }
}

$('#eth-save-btn')?.addEventListener('click', async () => {
  const btn = $('#eth-save-btn'); btn.disabled = true; btn.textContent = 'Applicazione…';
  const body = {
    type: 'ethernet', method: _netMethod.eth,
    address: $('#eth-address').value, gateway: $('#eth-gateway').value, dns: $('#eth-dns').value
  };
  const { ok, data } = await api('/api/network/config', { method: 'POST', body: JSON.stringify(body) });
  toast(data.message || (ok ? 'Ethernet configurata' : 'Errore'), ok ? 'ok' : 'err');
  btn.disabled = false; btn.textContent = 'Applica ethernet';
  if (ok) setTimeout(loadStatus, 3000);
});

$('#wifi-ip-save-btn')?.addEventListener('click', async () => {
  const btn = $('#wifi-ip-save-btn'); btn.disabled = true; btn.textContent = 'Applicazione…';
  const body = {
    type: 'wifi', method: _netMethod.wifi,
    address: $('#wifi-ip-address').value, gateway: $('#wifi-ip-gateway').value, dns: $('#wifi-ip-dns').value
  };
  const { ok, data } = await api('/api/network/config', { method: 'POST', body: JSON.stringify(body) });
  toast(data.message || (ok ? 'WiFi IP configurato' : 'Errore'), ok ? 'ok' : 'err');
  btn.disabled = false; btn.textContent = 'Applica WiFi';
  if (ok) setTimeout(loadStatus, 3000);
});

// ── WiFi ─────────────────────────────────────────────────────────────────
let _selectedSsid = '';

async function loadWifiStatus() {
  const { data } = await api('/api/status');
  const ind = $('#wifi-indicator'), txt = $('#wifi-status-text'), sub = $('#wifi-status-sub');
  if (data.type === 'wifi') {
    ind.className = 'status-indicator active'; ind.textContent = '📶';
    txt.textContent = `Connesso: ${data.ssid || 'WiFi'}`;
    sub.textContent = data.ip || '';
  } else if (data.type === 'ethernet') {
    ind.className = 'status-indicator'; ind.textContent = '🔌';
    txt.textContent = 'Ethernet connessa';
    sub.textContent = data.ip || '';
  } else {
    ind.className = 'status-indicator'; ind.textContent = '📶';
    txt.textContent = 'Non connesso';
    sub.textContent = '';
  }
}

$('#wifi-scan-btn')?.addEventListener('click', async () => {
  const btn = $('#wifi-scan-btn');
  btn.disabled = true; btn.textContent = '🔍 Ricerca in corso…';
  const { ok, data } = await api('/api/wifi/scan');
  btn.disabled = false; btn.textContent = '🔍 Cerca reti WiFi';
  if (!ok || !data.networks?.length) { toast('Nessuna rete trovata', 'err'); return; }
  const list = $('#wifi-list');
  list.innerHTML = data.networks.map(n => `
    <div class="cam-card" style="cursor:pointer" onclick="selectWifi('${esc(n.ssid)}')">
      <div class="cam-card-info">
        <div class="cam-card-name">${esc(n.ssid)}</div>
        <div class="cam-card-url">${n.security !== 'open' ? '🔒 ' : '🔓 '}${n.signal}% — ${n.security}</div>
      </div>
    </div>`).join('');
  $('#wifi-networks').style.display = 'block';
});

window.selectWifi = ssid => {
  _selectedSsid = ssid;
  $('#wifi-ssid-label').textContent = `Password per "${ssid}"`;
  $('#wifi-password').value = '';
  $('#wifi-connect-form').classList.remove('hidden');
  $('#wifi-password').focus();
};

$('#wifi-connect-btn')?.addEventListener('click', async () => {
  const btn = $('#wifi-connect-btn');
  btn.disabled = true; btn.textContent = 'Connessione…';
  const { ok, data } = await api('/api/wifi/connect', {
    method: 'POST',
    body: JSON.stringify({ ssid: _selectedSsid, password: $('#wifi-password').value })
  });
  toast(data.message || (ok ? `Connesso a ${_selectedSsid}` : 'Errore'), ok ? 'ok' : 'err');
  btn.disabled = false; btn.textContent = 'Connetti';
  if (ok) {
    $('#wifi-connect-form').classList.add('hidden');
    $('#wifi-networks').style.display = 'none';
    setTimeout(loadWifiStatus, 3000);
  }
});

$('#wifi-cancel-btn')?.addEventListener('click', () => {
  $('#wifi-connect-form').classList.add('hidden');
  _selectedSsid = '';
});

// ── Apply / Setup mode ────────────────────────────────────────────────────
$('#apply-btn')?.addEventListener('click', async () => {
  const { ok, data } = await api('/api/apply', { method: 'POST' });
  toast(data.message || (ok ? 'Riavvio in corso…' : 'Errore'), ok ? 'ok' : 'err');
});

// ── Init ──────────────────────────────────────────────────────────────────
(async () => {
  const ok = await initAuth();
  if (!ok) return;

  // Ripristina il tab salvato al refresh (prima di caricare i dati)
  try {
    const saved = localStorage.getItem('cv-tab');
    if (saved) switchTab(saved);
  } catch(e) {}

  // Load site name (public)
  await loadSiteName();

  // Load all data in parallel
  await Promise.all([
    loadStatus(),
    loadCameras(),
    loadViews(),
    loadSettings(),
    loadVpnStatus(),
    loadPlaceholder(),
    loadWallpaper(),
    loadUsers(),
  ]);

  // Poll status every 30s
  setInterval(loadStatus, 30000);
  loadWifiStatus();
  loadNetworkConfig();
})();

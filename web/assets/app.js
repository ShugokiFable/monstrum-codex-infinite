const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];

const state = {
  entries: [], facets: { families: [], habitats: [], rarities: [], catalog_counts: {} }, total: 0,
  selected: null, draft: null, editingId: null, editorSeed: null, exportId: null,
  filters: { query: '', family: '', habitat: '', rarity: '', favorites: false, catalog_kind: '', sort: 'name' },
  settings: {}, models: [], currentView: 'official',
};

const els = {
  grid: $('#entryGrid'), empty: $('#emptyState'), visibleCount: $('#visibleCount'), countAll: $('#countAll'), countFav: $('#countFav'),
  countOfficial: $('#countOfficial'), countAI: $('#countAI'), countUser: $('#countUser'),
  search: $('#searchInput'), family: $('#familyFilter'), habitat: $('#habitatFilter'), rarity: $('#rarityFilter'), sort: $('#sortFilter'),
  panel: $('#detailPanel'), veil: $('#panelVeil'), detail: $('#detailContent'), page: $('#specimenPage'),
  forgeDialog: $('#forgeDialog'), editorDialog: $('#editorDialog'), imageDialog: $('#imageDialog'), settingsDialog: $('#settingsDialog'),
  exportDialog: $('#exportDialog'), helpDialog: $('#helpDialog'),
};

function esc(value = '') {
  return String(value).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}
function attr(value = '') { return esc(value).replace(/\n/g, '&#10;'); }
function debounce(fn, delay = 250) { let t; return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), delay); }; }
function hashHue(s = '') { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) % 360; return h; }
function accent(entry) {
  const h = hashHue(`${entry.family}${entry.name}`);
  return { a: `hsla(${h}, 82%, 58%, .26)`, b: `hsl(${(h + 315) % 360}, 28%, 14%)` };
}
function initials(name = '?') { return name.split(/\s+/).slice(0, 2).map(x => x[0]).join('').toUpperCase(); }
function catalogLabel(kind = 'user') { return ({official:'Official', ai:'AI Forged', user:'User'})[kind] || 'User'; }
function catalogIcon(kind = 'user') { return ({official:'◆', ai:'✦', user:'◇'})[kind] || '◇'; }
function safeHttpUrl(value = '') { try { const u = new URL(String(value), window.location.origin); return ['http:','https:'].includes(u.protocol) ? u.href : ''; } catch { return ''; } }
function toast(message, type = '') {
  const node = document.createElement('div'); node.className = `toast ${type}`; node.textContent = message;
  $('#toastStack').append(node); setTimeout(() => node.remove(), 4200);
}
async function api(path, options = {}) {
  const response = await fetch(path, { headers: options.body instanceof FormData ? {} : {'Content-Type':'application/json'}, ...options });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try { const data = await response.json(); detail = data.detail || detail; } catch {}
    throw new Error(detail);
  }
  const type = response.headers.get('content-type') || '';
  return type.includes('application/json') ? response.json() : response;
}

function officialMedia(entry) {
  const extra = entry.extra || {};
  const raw = extra.official_media && typeof extra.official_media === 'object' ? extra.official_media : {};
  let mugshot = raw.mugshot && typeof raw.mugshot === 'object' ? raw.mugshot : null;
  if (!mugshot) {
    const legacyPath = extra.official_mugshot_path || extra.official_portrait_path || entry.image_path || '';
    const legacyFilename = extra.official_image_filename || '';
    if (legacyPath && (String(extra.official_image_category || '').toLowerCase() === 'mugshot' || String(legacyFilename).toLowerCase().includes('mug'))) {
      mugshot = {kind:'mugshot', path:legacyPath, url:entry.image_url || '', filename:legacyFilename, file_page:extra.official_image_file_page || ''};
    }
  }
  const clean = value => Array.isArray(value) ? value.filter(x => x && typeof x === 'object') : [];
  return {
    complete: !!raw.complete,
    failures: Array.isArray(raw.failures) ? raw.failures.map(String) : [],
    mugshot,
    portraits: clean(raw.portraits || extra.official_portraits),
    entryImages: clean(raw.entry_images || extra.official_entry_images),
  };
}
function assetSrc(asset) { return String(asset?.path || asset?.url || ''); }
function officialBrowserCandidates(entry) {
  const out = [], push = value => { const url = safeHttpUrl(value); if (url && !out.includes(url)) out.push(url); };
  const media = officialMedia(entry);
  push(media.mugshot?.url || '');
  if (entry.id && media.mugshot?.url) out.push(`/api/official/${entry.id}/image`);
  return out;
}
function imageAssetCandidates(entry, {detail = false} = {}) {
  const out = [], push = (value, kind = '') => { if (value && !out.some(item => item.src === value)) out.push({src:value, kind}); };
  if (entry.catalog_kind === 'official') {
    const media = officialMedia(entry);
    // Detail heroes prefer full art. Archive cards prefer the compact mugshot,
    // but now fall back through every locally cached official media class instead
    // of showing a blank rune when one filename failed to resolve.
    if (detail) {
      media.portraits.forEach(asset => push(assetSrc(asset), 'portrait'));
      push(assetSrc(media.mugshot), 'mugshot');
    } else {
      push(assetSrc(media.mugshot), 'mugshot');
      media.portraits.forEach(asset => push(assetSrc(asset), 'portrait'));
    }
    media.entryImages.forEach(asset => push(assetSrc(asset), 'entry'));
    if (state.settings.remoteOfficialImages === true) officialBrowserCandidates(entry).forEach(src => push(src, 'mugshot'));
  } else {
    push(entry.image_path || '', 'portrait');
    push(safeHttpUrl(entry.image_url || ''), 'portrait');
  }
  return out;
}
function imageCandidates(entry, options = {}) { return imageAssetCandidates(entry, options).map(item => item.src); }
function imageSource(entry) { return imageCandidates(entry)[0] || ''; }
function officialMediaClass(kind = '') {
  return ({portrait:'official-full-portrait', mugshot:'official-mugshot', entry:'official-entry-page'})[kind] || '';
}
function imageTag(entry, {detail = false, className = ''} = {}) {
  const assets = imageAssetCandidates(entry, {detail});
  if (!assets.length) return '';
  const queue = encodeURIComponent(JSON.stringify(assets.slice(1)));
  const fallback = detail ? '' : ` data-fallback-rune="${attr(initials(entry.name))}"`;
  const mediaClass = entry.catalog_kind === 'official' ? officialMediaClass(assets[0].kind) : '';
  const classes = [className, mediaClass].filter(Boolean).join(' ');
  return `<img src="${attr(assets[0].src)}" alt="${attr(entry.name)}" loading="lazy" referrerpolicy="no-referrer" data-image-queue="${attr(queue)}"${fallback}${detail?' data-detail-image':''}${classes?` class="${attr(classes)}"`:''} />`;
}
function runeHtml(entry) { return `<div class="card-rune">${esc(initials(entry.name))}</div>`; }
function nextImageCandidate(img) {
  let queue = [];
  try { queue = JSON.parse(decodeURIComponent(img.dataset.imageQueue || '%5B%5D')); } catch {}
  const raw = queue.shift();
  if (raw) {
    const next = typeof raw === 'string' ? {src:raw, kind:''} : raw;
    img.dataset.imageQueue = encodeURIComponent(JSON.stringify(queue));
    img.classList.remove('official-mugshot', 'official-full-portrait', 'official-entry-page');
    const mediaClass = officialMediaClass(next.kind || '');
    if (mediaClass) img.classList.add(mediaClass);
    img.src = next.src;
    return true;
  }
  return false;
}
function wireImageFallbacks(root = document) {
  $$('img[data-image-queue]', root).forEach(img => img.addEventListener('error', () => {
    if (nextImageCandidate(img)) return;
    if (img.dataset.fallbackRune !== undefined) {
      const fallback = document.createElement('div'); fallback.className = 'card-rune'; fallback.textContent = img.dataset.fallbackRune || '?';
      img.replaceWith(fallback);
    } else {
      img.remove();
    }
  }));
}

async function loadEntries() {
  els.grid.innerHTML = Array.from({length: 8}, () => '<div class="loading-card"></div>').join('');
  const q = new URLSearchParams();
  Object.entries(state.filters).forEach(([k,v]) => { if (v !== '' && v !== false) q.set(k, String(v)); });
  q.set('limit', '2000');
  try {
    const data = await api(`/api/entries?${q}`);
    state.entries = data.items; state.total = data.total; state.facets = data.facets;
    renderFilters(); renderEntries(); updateCounts();
  } catch (e) { els.grid.innerHTML = ''; toast(`Could not load codex: ${e.message}`, 'error'); }
}

function renderFilters() {
  const refill = (el, items, label, selected) => {
    const keep = selected || el.value;
    el.innerHTML = `<option value="">${label}</option>` + items.map(v => `<option value="${attr(v)}">${esc(v)}</option>`).join('');
    el.value = keep;
  };
  refill(els.family, state.facets.families, 'Every family', state.filters.family);
  refill(els.habitat, state.facets.habitats, 'Every habitat', state.filters.habitat);
  refill(els.rarity, state.facets.rarities, 'Every rarity', state.filters.rarity);
}

function renderEntries() {
  document.body.classList.toggle('compact', !!state.settings.compactCards);
  animateCount(els.visibleCount, state.entries.length);
  els.empty.classList.toggle('hidden', state.entries.length > 0);
  els.grid.classList.toggle('hidden', state.entries.length === 0);
  if (state.currentView === 'all') {
    const groups = [
      ['official', 'Official Archive', 'Canonical source-linked entries'],
      ['ai', 'AI-Forged Bestiary', 'Original entries. Portraits are generated, not downloaded from the Official cache.'],
      ['user', 'User Creations', 'Your authored and imported entries'],
    ];
    els.grid.innerHTML = groups.map(([kind, title, note]) => {
      const items = state.entries.filter(entry => entry.catalog_kind === kind);
      if (!items.length) return '';
      return `<div class="library-divider library-${kind}"><div><span>${catalogIcon(kind)}</span><strong>${esc(title)}</strong></div><small>${esc(note)}</small><b>${items.length}</b></div>${items.map((entry, i) => cardHtml(entry, i)).join('')}`;
    }).join('');
  } else {
    els.grid.innerHTML = state.entries.map((entry, i) => cardHtml(entry, i)).join('');
  }
  wireImageFallbacks(els.grid);
  bootScenes(els.grid);
  $$('.specimen-card', els.grid).forEach(card => card.addEventListener('click', () => openDetail(Number(card.dataset.id))));
  $$('.fav-card', els.grid).forEach(btn => btn.addEventListener('click', async e => {
    e.stopPropagation();
    const id = Number(btn.closest('.specimen-card').dataset.id);
    const entry = state.entries.find(x => x.id === id); if (!entry) return;
    if (!entry.favorite) {
      const r = btn.getBoundingClientRect();
      heartBurst(r.left + r.width / 2, r.top + r.height / 2);
      btn.classList.remove('fav-pop'); void btn.offsetWidth; btn.classList.add('fav-pop');
    }
    await updateEntry(id, { ...entry, favorite: !entry.favorite }, false);
  }));
  $$('.card-art-action', els.grid).forEach(btn => btn.addEventListener('click', e => {
    e.stopPropagation();
    const entry = state.entries.find(x => x.id === Number(btn.dataset.imageId));
    if (entry) openImageStudio(entry);
  }));
}

function cardHtml(entry, index = 0) {
  const assets = imageAssetCandidates(entry);
  const c = accent(entry), art = assets.length ? imageTag(entry) : runeHtml(entry);
  const missingArt = entry.catalog_kind !== 'official' && !assets.length;
  const artAction = missingArt ? `<button type="button" class="card-art-action" data-image-id="${entry.id}"><span>✦</span>${entry.catalog_kind === 'ai' ? 'Generate portrait' : 'Add portrait'}</button>` : '';
  const pips = Array.from({length:5},(_,i)=>`<i class="${i < entry.danger ? 'on':''}"></i>`).join('');
  const scene = livingSceneFor(entry);
  const sceneLayer = scene ? `<canvas class="living-scene" data-scene="${scene}" aria-hidden="true"></canvas>` : '';
  const glyph = scene && scene !== 'default' ? `<span class="scene-glyph" title="Living space">${SCENES[scene].glyph}</span>` : '';
  const delay = (index % 14) * 42;
  const foil = ['Rare', 'Mythic', 'Legendary'].includes(entry.rarity) ? ' rarity-foil' : '';
  const heat = Math.max(1, Math.min(3, Math.ceil((Number(entry.danger) || 0) / 1.7)));
  return `<article class="specimen-card${foil} catalog-${attr(entry.catalog_kind)}" data-id="${entry.id}" data-danger="${heat}" style="--accent-a:${c.a};--accent-b:${c.b};animation-delay:${delay}ms">
    <div class="card-art">${sceneLayer}${art}${artAction}</div>
    <div class="card-top"><div class="badge-stack"><span class="badge catalog-badge ${attr(entry.catalog_kind)}">${catalogIcon(entry.catalog_kind)} ${esc(catalogLabel(entry.catalog_kind))}</span><span class="badge">${esc(entry.rarity)}</span></div><button class="fav-card ${entry.favorite?'active':''}" title="Favorite">${entry.favorite?'♥':'♡'}</button></div>
    <div class="card-copy"><h3>${hl(entry.name)}</h3><span class="latin">${esc(entry.species || entry.family)}</span><p>${hl(entry.summary)}</p>
    <div class="card-meta"><span>${esc(entry.family)}</span><span>•</span>${glyph}<span>${esc(entry.habitat)}</span><span class="danger-pips" title="Danger ${entry.danger}/5">${pips}</span></div></div>
  </article>`;
}

function updateCounts() {
  const c = state.facets.catalog_counts || {};
  els.countAll.textContent = Number(c.all ?? state.total).toLocaleString();
  els.countFav.textContent = Number(c.favorites ?? 0).toLocaleString();
  els.countOfficial.textContent = Number(c.official ?? 0).toLocaleString();
  els.countAI.textContent = Number(c.ai ?? 0).toLocaleString();
  els.countUser.textContent = Number(c.user ?? 0).toLocaleString();
}

function officialAssetLabel(asset, kind, index) {
  if (kind === 'mugshot') return 'Mugshot';
  if (kind === 'portrait') return `Portrait ${asset.index ?? index}`;
  const language = String(asset.language || '').toUpperCase();
  return `Entry ${language ? `${language} ` : ''}Page ${asset.index ?? index + 1}`;
}
function officialMediaSection(entry) {
  if (entry.catalog_kind !== 'official') return '';
  const media = officialMedia(entry);
  const groups = [
    ['Mugshot', media.mugshot ? [media.mugshot] : [], 'mugshot'],
    ['Portraits', media.portraits, 'portrait'],
    ['Entry Images', media.entryImages, 'entry'],
  ];
  const cards = groups.map(([title, assets, kind]) => {
    const body = assets.length ? assets.map((asset, index) => {
      const src = assetSrc(asset);
      if (!src) return '';
      const label = officialAssetLabel(asset, kind, index);
      const source = safeHttpUrl(asset.file_page || '');
      return `<button type="button" class="official-media-thumb media-${kind}" data-media-src="${attr(src)}" data-media-title="${attr(`${entry.name} · ${label}`)}" data-media-source="${attr(source)}">
        <img src="${attr(src)}" alt="${attr(label)}" loading="lazy" referrerpolicy="no-referrer" />
        <span><strong>${esc(label)}</strong><small>${esc(asset.filename || '')}</small></span>
      </button>`;
    }).join('') : `<div class="official-media-empty">No ${kind === 'entry' ? 'entry pages' : kind === 'portrait' ? 'standalone portraits' : 'mugshot'} cached.</div>`;
    return `<div class="official-media-group"><header><h4>${title}</h4><b>${assets.length}</b></header><div class="official-media-strip">${body}</div></div>`;
  }).join('');
  const status = media.complete ? 'Media index complete' : 'Media index incomplete or awaiting repair';
  return `<section class="prose-section official-media-section"><div class="official-media-heading"><div><h3>Official Media Archive</h3><p>Cards prefer the mugshot and automatically fall back to a full portrait or entry page. The detail hero prefers full portrait art.</p></div><span class="media-status ${media.complete ? 'complete' : ''}">${status}</span></div>${cards}</section>`;
}
function openOfficialMedia(button) {
  const dialog = $('#officialMediaDialog');
  const image = $('#officialMediaImage');
  const title = $('#officialMediaTitle');
  const source = $('#officialMediaSource');
  image.src = button.dataset.mediaSrc || '';
  image.alt = button.dataset.mediaTitle || 'Official media';
  title.textContent = button.dataset.mediaTitle || 'Official Media';
  const href = safeHttpUrl(button.dataset.mediaSource || '');
  source.classList.toggle('hidden', !href);
  if (href) source.href = href;
  dialog.showModal();
}
function wireOfficialMedia(root = document) {
  $$('.official-media-thumb', root).forEach(button => button.addEventListener('click', () => openOfficialMedia(button)));
  $$('img', root).forEach(img => img.addEventListener('error', () => img.closest('.official-media-thumb')?.classList.add('media-missing')));
}

/* Shared per-entry detail markup. Panel gets `more:false`; the immersive
   "other page" gets `more:true`, which adds the Living Environment stage. */
function entryMarkup(e, more = false) {
  const c = accent(e), image = imageTag(e, {detail:true});
  const candidates = imageCandidates(e, {detail:true});
  const section = (id, title, text) => text ? `<section class="prose-section" id="sec-${id}"><h3>${title}</h3><p>${esc(text)}</p></section>` : '';
  const cp = e.codex_profile;
  const profileCard = cp ? `<section class="prose-section codex-profile" id="sec-profile"><h3>Naturalist Profile</h3><div class="profile-grid">
      <div class="profile-item"><small>Diet</small><p>${esc(cp.diet)}</p></div>
      <div class="profile-item"><small>Behavior</small><p>${esc(cp.behavior)}</p></div>
      <div class="profile-item"><small>Likes</small><p>${esc(cp.likes)}</p></div>
      <div class="profile-item"><small>Dislikes</small><p>${esc(cp.dislikes)}</p></div>
      <div class="profile-item"><small>Beloved Terrain</small><p>${esc(cp.loved_environment)}</p></div>
      <div class="profile-item"><small>Avoids</small><p>${esc(cp.hated_environment)}</p></div>
    </div></section>` : '';
  const chips = arr => `<div class="chips">${(arr||[]).map(x=>`<span class="chip">${esc(x)}</span>`).join('')}</div>`;
  const sourceHref = safeHttpUrl(e.source_url || '');
  const sourceLink = sourceHref ? `<a class="button ghost" href="${attr(sourceHref)}" target="_blank" rel="noopener noreferrer">Open Canonical Source</a>` : '';
  const hasRealLore = !!(e.lore || '').trim();
  const officialNotice = e.catalog_kind === 'official' ? `<section class="prose-section official-reference"><h3>Official Reference</h3>${hasRealLore ? '' : '<p>This record indexes a canonical Monster Girl Encyclopedia profile. The source page remains the authority for its full prose and artwork.</p>'}<div class="art-actions">${sourceLink}${hasRealLore ? '' : '<button class="button primary" id="cacheOfficialImageBtn">Open Real-Browser Cache</button>'}</div></section>` : '';
  const aliasesRow = (e.aliases || []).length ? `<div class="aliases-row"><small>Also known as</small> ${(e.aliases).map(a=>`<span class="alias">${esc(a)}</span>`).join('')}</div>` : '';
  const dexTabs = [['profile','Profile'],['lore','Lore'],['appearance','Looks'],['physiology','Body'],['ecology','Ecology'],['culture','Culture'],['temperament','Temper'],['abilities','Abilities'],['weaknesses','Weaknesses']];
  const dexNav = `<div class="dex-nav">${dexTabs.map(([id,label])=>`<button type="button" data-sec="${id}">${label}</button>`).join('')}</div>`;
  /* The "other page" exclusive: a big living picture of where this specimen dwells */
  const habitatSection = more ? `<section class="prose-section habitat-section" id="sec-habitat"><h3>Living Environment</h3>
    <div class="habitat-stage" data-danger="${e.danger || 0}"><canvas class="living-scene" data-scene="${livingSceneFor(e) || 'default'}" aria-hidden="true"></canvas></div>
    ${cp ? `<p class="habitat-line"><strong>Beloved:</strong> ${esc(cp.loved_environment)}</p><p class="habitat-line"><strong>Avoids:</strong> ${esc(cp.hated_environment)}</p>` : ''}
  </section>` : '';
  const showMoreBtn = more ? '' : `<button type="button" id="showMoreBtn" class="button primary show-more-btn">Show more info ▸ living environment, behavior &amp; lore</button>`;
  const html = `<section class="detail-hero catalog-${attr(e.catalog_kind)}" style="--accent-a:${c.a};--accent-b:${c.b}">${image}<div class="detail-title">
    <div class="detail-badges"><span class="badge dex-no">№ ${String(e.id).padStart(3,'0')}</span><span class="badge catalog-badge ${attr(e.catalog_kind)}">${catalogIcon(e.catalog_kind)} ${esc(catalogLabel(e.catalog_kind))}</span><span class="badge">${esc(e.rarity)}</span><span class="badge">Danger ${e.danger}/5</span><span class="badge">${esc(e.rating)}</span></div>
    <h2>${esc(e.name)}</h2><p class="summary">${esc(e.summary)}</p>${aliasesRow}</div></section>
    <div class="detail-body">${dexNav}${showMoreBtn}
      <div class="fact-grid"><div class="fact"><small>Library</small><strong>${esc(catalogLabel(e.catalog_kind))}</strong></div><div class="fact"><small>Species</small><strong>${esc(e.species)}</strong></div><div class="fact"><small>Family</small><strong>${esc(e.family)}</strong></div><div class="fact"><small>Alignment</small><strong>${esc(e.alignment)}</strong></div><div class="fact"><small>Origin</small><strong>${esc(e.origin)}</strong></div><div class="fact"><small>Habitat</small><strong>${sceneGlyph(e) ? `<span class="scene-glyph">${sceneGlyph(e)}</span> ` : ''}${esc(e.habitat)}</strong></div><div class="fact"><small>Source</small><strong>${esc(e.source_name || e.source_kind)}</strong></div></div>
      ${habitatSection}${officialNotice}${officialMediaSection(e)}${profileCard}${section('lore','Field Lore', e.lore)}${section('appearance','Appearance', e.appearance)}${section('physiology','Physiology', e.physiology)}${section('ecology','Ecology', e.ecology)}${section('culture','Culture', e.culture)}${section('temperament','Temperament', e.temperament)}
      ${(e.abilities||[]).length ? `<section class="prose-section"><h3>Abilities</h3>${chips(e.abilities)}</section>` : ''}${(e.weaknesses||[]).length ? `<section class="prose-section"><h3>Weaknesses</h3>${chips(e.weaknesses)}</section>` : ''}<section class="prose-section"><h3>Tags</h3>${chips(e.tags)}</section>
      <section class="prose-section"><h3>Generated Portrait & Roleplay</h3><p>${candidates.length ? 'A display image is available. Official source media stays in the gallery above; generated or attached art can be managed here.' : 'No display image has been attached or resolved yet.'}</p><div class="art-actions"><button class="button primary" id="detailImageBtn">${e.image_path?'Replace':'Attach / Generate'} Portrait</button><button class="button ghost" id="detailExportBtn">SillyTavern Export</button></div></section>
    </div>`;
  return html;
}

/* Every interactive piece of an entry view, scoped to whatever container it was rendered into */
function wireEntry(root, e, scroller) {
  wireImageFallbacks(root);
  wireOfficialMedia(root);
  const hero = $('.detail-hero', root);
  if (hero) attachHeroScene(hero, e);
  bootScenes(root); // habitat stage canvases live outside the hero — boot them too
  $('#favoriteDetail').textContent = `${e.favorite ? '♥' : '♡'} ${e.favorite ? 'Favorited' : 'Favorite'}`;
  $('#editDetail').textContent = e.catalog_kind === 'official' ? 'Clone to User' : 'Edit';
  const imgBtn = $('#detailImageBtn', root); if (imgBtn) imgBtn.addEventListener('click', () => openImageStudio(e));
  const expBtn = $('#detailExportBtn', root); if (expBtn) expBtn.addEventListener('click', () => openExport(e.id));
  const cacheBtn = $('#cacheOfficialImageBtn', root); if (cacheBtn) cacheBtn.addEventListener('click', () => cacheOfficialEntry(e.id, cacheBtn));
  const moreBtn = $('#showMoreBtn', root); if (moreBtn) moreBtn.addEventListener('click', () => showMore());
  const nav = $('.dex-nav', root);
  if (nav) {
    const secs = [...$$('.prose-section[id^="sec-"]', root)];
    secs.forEach((s, i) => s.setAttribute('data-no', String(i + 1).padStart(2, '0')));
    $$('button[data-sec]', nav).forEach(b => { if (!$(`#sec-${b.dataset.sec}`, root)) b.remove(); });
    nav.addEventListener('click', ev => { const b = ev.target.closest('button[data-sec]'); if (b) $(`#sec-${b.dataset.sec}`, root)?.scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block:'start'}); });
    const mark = () => {
      let cur = secs[0]?.id;
      const base = scroller.getBoundingClientRect().top;
      for (const s of secs) if (s.getBoundingClientRect().top - base <= 150) cur = s.id;
      if (scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 4) cur = secs[secs.length - 1].id;
      $$('.dex-nav button', root).forEach(b => b.classList.toggle('active', `sec-${b.dataset.sec}` === cur));
    };
    scroller.addEventListener('scroll', mark, {passive:true});
    mark();
  }
}

/* The "other page": full-screen specimen dossier with its habitat stage.
   Reuses the same markup builder; the action bar physically MOVES here so
   its existing listeners (close/favorite/edit/settings/nav) keep working. */
function renderSpecimenPage(e) {
  const bar = $('.detail-head'); // wherever the bar currently lives (panel or previous page render)
  els.page.innerHTML = entryMarkup(e, true);
  if (bar) els.page.appendChild(bar);
  document.body.classList.add('specimen-open');
  els.page.setAttribute('aria-hidden', 'false');
  wireEntry(els.page, e, els.page);
  els.page.scrollTop = 0;
  window.scrollTo({ top: 0, behavior: 'auto' });
}
function showMore() { const e = state.selected; if (e) renderSpecimenPage(e); }

async function openDetail(id) {
  try { state.selected = await api(`/api/entries/${id}`); } catch (e) { toast(e.message, 'error'); return; }
  const e = state.selected;
  /* Clicking a card NEVER leaves the codex view — the side panel opens on top.
     Arrow-key browsing while the page is open just repaints the page. */
  if (document.body.classList.contains('specimen-open')) { renderSpecimenPage(e); setNavState(); return; }
  els.detail.innerHTML = entryMarkup(e, false);
  els.panel.classList.add('open'); els.veil.classList.add('open'); els.panel.setAttribute('aria-hidden', 'false');
  const scroller = [els.detail, els.panel].find(x => x.scrollHeight > x.clientHeight + 2) || els.detail;
  wireEntry(els.detail, e, scroller);
  setNavState(); pushRecent(e); renderRecent();
}
function closeDetail() {
  if (!document.body.classList.contains('specimen-open')) {
    els.panel.classList.remove('open'); els.veil.classList.remove('open'); els.panel.setAttribute('aria-hidden', 'true');
    renderRecent();
    return;
  }
  document.body.classList.remove('specimen-open');
  const bar = $('.detail-head', els.page);
  els.page.setAttribute('aria-hidden', 'true');
  els.page.innerHTML = '';
  if (bar) els.panel.insertBefore(bar, els.panel.firstChild); // return the action bar to the panel
  renderRecent();
}

async function cacheOfficialEntry(id, button) {
  const original = button.textContent; button.disabled = true; button.textContent = 'Opening browser…';
  try { await cacheAllOfficial(); await openDetail(id); }
  catch (e) { toast(`Could not run real-browser cache: ${e.message}`, 'error'); }
  finally { button.disabled = false; button.textContent = original; }
}

async function cloneOfficialEntry(entry) {
  const clone = {...entry};
  delete clone.id; delete clone.slug; delete clone.created_at; delete clone.updated_at;
  clone.catalog_kind = 'user';
  clone.source_kind = 'user';
  clone.source_name = `User adaptation of ${entry.source_name || 'official reference'}`;
  clone.tags = [...new Set([...(entry.tags || []), 'user-adaptation', 'official-reference-derived'])];
  clone.favorite = false;
  try {
    const saved = await api('/api/entries', {method:'POST', body:JSON.stringify({data:clone})});
    closeDetail(); await loadEntries(); openEditor(saved); toast(`Cloned ${entry.name} into User Creations.`);
  } catch (e) { toast(`Clone failed: ${e.message}`, 'error'); }
}

async function updateEntry(id, data, reopen = true) {
  try {
    const saved = await api(`/api/entries/${id}`, { method:'PUT', body: JSON.stringify({data}) });
    if (state.selected?.id === id) state.selected = saved;
    await loadEntries(); if (reopen) await openDetail(id); return saved;
  } catch (e) { toast(`Save failed: ${e.message}`, 'error'); throw e; }
}

const editorDefs = [
  ['catalog_kind','Library','select',['user','ai','official']], ['name','Name','input'], ['species','Species / scholarly name','input'], ['family','Family','input'], ['rarity','Rarity','select', ['Common','Uncommon','Rare','Legendary','Mythic']], ['danger','Danger 0–5','number'], ['alignment','Alignment','input'],
  ['origin','Origin','input'], ['habitat','Habitat','input'], ['rating','Rating','select',['SFW','Suggestive','Mature']], ['source_name','Source name','input'], ['source_url','Source URL','input'], ['image_url','Remote image URL','input'], ['summary','Summary','textarea-wide'],
  ['lore','Field lore','textarea-wide'], ['appearance','Appearance','textarea-wide'], ['physiology','Physiology','textarea-wide'], ['ecology','Ecology','textarea-wide'], ['culture','Culture','textarea-wide'], ['temperament','Temperament','textarea-wide'],
  ['abilities','Abilities (one per line)','textarea'], ['weaknesses','Weaknesses (one per line)','textarea'], ['aliases','Aliases (one per line)','textarea'], ['tags','Tags (one per line)','textarea'],
  ['image_prompt','Image prompt','textarea-wide'], ['negative_prompt','Negative prompt','textarea-wide'], ['st_personality','SillyTavern personality','textarea-wide'], ['st_scenario','SillyTavern scenario','textarea-wide'], ['st_first_message','SillyTavern first message','textarea-wide'], ['st_example_dialogue','SillyTavern example dialogue','textarea-wide']
];
function openEditor(entry = null) {
  state.editingId = entry?.id || null; state.editorSeed = entry || null;
  $('#editorTitle').textContent = entry?.id ? `Edit ${entry.name}` : entry?.name ? `Review ${entry.name}` : 'New User Entry';
  $('#deleteEntry').classList.toggle('hidden', !entry?.id || entry?.catalog_kind === 'official');
  $('#editorFields').innerHTML = editorDefs.map(([key,label,type,options]) => {
    let value = entry?.[key] ?? (key === 'catalog_kind' ? 'user' : '');
    if (Array.isArray(value)) value = value.join('\n');
    const wide = type.includes('wide') ? 'wide' : '';
    if (type.startsWith('textarea')) return `<label class="field ${wide}">${label}<textarea data-key="${key}" rows="${wide?'5':'4'}">${esc(value)}</textarea></label>`;
    if (type === 'select') return `<label class="field ${wide}">${label}<select data-key="${key}">${options.map(o=>`<option value="${attr(o)}" ${o===value?'selected':''}>${esc(key==='catalog_kind'?catalogLabel(o):o)}</option>`).join('')}</select></label>`;
    return `<label class="field ${wide}">${label}<input data-key="${key}" type="${type}" value="${attr(value)}" ${key==='danger'?'min="0" max="5"':''}/></label>`;
  }).join('');
  els.editorDialog.showModal();
}
function readEditor() {
  const data = {...(state.editorSeed || {})};
  $$('[data-key]', $('#editorFields')).forEach(el => {
    const key = el.dataset.key; let value = el.value;
    if (['abilities','weaknesses','aliases','tags'].includes(key)) value = value.split('\n').map(x=>x.trim()).filter(Boolean);
    if (key === 'danger') value = Number(value || 0);
    data[key] = value;
  });
  data.adult = true;
  data.catalog_kind = data.catalog_kind || 'user';
  data.source_kind = data.catalog_kind === 'official' ? 'official' : data.catalog_kind === 'ai' ? 'ai' : 'user';
  if (data.catalog_kind === 'user' && !data.source_name) data.source_name = 'User-created';
  return data;
}

async function saveEditor(ev) {
  ev.preventDefault(); const data = readEditor();
  try {
    const saved = state.editingId ? await api(`/api/entries/${state.editingId}`, {method:'PUT', body:JSON.stringify({data})}) : await api('/api/entries', {method:'POST', body:JSON.stringify({data})});
    els.editorDialog.close(); toast(`Saved ${saved.name} to ${catalogLabel(saved.catalog_kind)}`); await loadEntries(); await openDetail(saved.id);
  } catch (e) { toast(e.message, 'error'); }
}

async function runForge(ev) {
  ev.preventDefault();
  const model = $('#forgeModel').value || state.settings.openrouterModel;
  const apiKey = state.settings.openrouterKey || $('#openrouterKey').value;
  if (!apiKey || !model) { toast('Set an OpenRouter key and model in Settings first.', 'error'); return; }
  const button = $('#forgeGenerate'), status = $('#forgeStatus');
  button.disabled = true; button.textContent = 'Forging…'; status.textContent = 'The model is assembling anatomy, lore, ecology, and roleplay behavior.';
  $('#forgePreview').innerHTML = '<div class="preview-placeholder"><span>✦</span><strong>Forging the specimen…</strong><p>Structured generation is in progress.</p></div>';
  try {
    const draft = await api('/api/ai/lore', { method:'POST', body:JSON.stringify({
      api_key: apiKey, model, concept: $('#forgeConcept').value, world: $('#forgeWorld').value, tone: $('#forgeTone').value, mature: $('#forgeMature').checked
    }) });
    draft.catalog_kind = 'ai'; state.draft = draft; renderDraft(draft); status.textContent = 'Draft ready. Save it as-is or open the full editor.';
  } catch (e) { toast(`Forge failed: ${e.message}`, 'error'); $('#forgePreview').innerHTML = `<div class="preview-placeholder"><strong>Generation failed</strong><p>${esc(e.message)}</p></div>`; status.textContent = 'Generation failed.'; }
  finally { button.disabled = false; button.textContent = '✦ Generate Codex Draft'; }
}
function renderDraft(d) {
  $('#forgePreview').innerHTML = `<article class="draft-card"><div class="draft-cover"><div><span class="badge catalog-badge ai">✦ AI Forged</span><span class="badge">${esc(d.rarity)}</span><h3>${esc(d.name)}</h3><small>${esc(d.species)} · ${esc(d.family)}</small></div></div><div class="draft-content"><p>${esc(d.summary)}</p><div class="chips">${(d.tags||[]).slice(0,8).map(x=>`<span class="chip">${esc(x)}</span>`).join('')}</div><div class="draft-actions"><button class="button primary" id="saveDraftBtn">Save to AI Library</button><button class="button ghost" id="editDraftBtn">Review All Fields</button></div></div></article>`;
  $('#saveDraftBtn').addEventListener('click', async () => {
    try { const saved = await api('/api/entries', {method:'POST', body:JSON.stringify({data:{...d,catalog_kind:'ai'}})}); els.forgeDialog.close(); toast(`Forged ${saved.name}`); await loadEntries(); await openDetail(saved.id); } catch(e){toast(e.message,'error');}
  });
  $('#editDraftBtn').addEventListener('click', () => { els.forgeDialog.close(); openEditor({...d,catalog_kind:'ai'}); });
}

async function openImageStudio(entry) {
  state.selected = entry;
  $('#imagePrompt').value = entry.image_prompt || `${entry.name}, adult ${entry.species}, ${entry.appearance}, ${entry.habitat}, fantasy field guide portrait`;
  $('#negativePrompt').value = entry.negative_prompt || 'minor, child, low quality, malformed anatomy, extra limbs, text, watermark';
  $('#imageProvider').value = state.settings.defaultImageProvider || 'comfyui';
  $('#imagePreview').innerHTML = imageTag(entry, {detail:true}) || '<span>No portrait yet</span>';
  wireImageFallbacks($('#imagePreview'));
  updateImageProviderText(); els.imageDialog.showModal();
}
function updateImageProviderText() {
  const p = $('#imageProvider').value, status = $('#imageStatus'), btn = $('#imageGenerateBtn');
  const map = {
    comfyui: ['ComfyUI uses your saved API-format workflow.', 'Generate Portrait'], openai: ['Uses the OpenAI Images API and API billing.', 'Generate Portrait'], gemini: ['Uses the Gemini API and API billing.', 'Generate Portrait'],
    'manual-chatgpt': ['Copies the prompt and opens ChatGPT Images. Drag the finished image back here.', 'Copy Prompt & Open ChatGPT'], 'manual-gemini': ['Copies the prompt and opens Gemini. Drag the finished image back here.', 'Copy Prompt & Open Gemini']
  };
  status.textContent = map[p][0]; btn.textContent = map[p][1];
}
async function runImage(ev) {
  ev.preventDefault(); if (!state.selected) return;
  const provider = $('#imageProvider').value, prompt = $('#imagePrompt').value, negative = $('#negativePrompt').value;
  if (provider.startsWith('manual-')) {
    await navigator.clipboard.writeText(`${prompt}\n\nNegative prompt: ${negative}`);
    window.open(provider === 'manual-chatgpt' ? 'https://chatgpt.com/' : 'https://gemini.google.com/', '_blank', 'noopener');
    toast('Prompt copied. Generate in the subscription app, then attach the result.'); return;
  }
  const button = $('#imageGenerateBtn'); button.disabled = true; button.textContent = 'Rendering…';
  try {
    let workflow = null;
    if (provider === 'comfyui') { try { workflow = JSON.parse(state.settings.comfyWorkflow || '{}'); } catch { throw new Error('Saved ComfyUI workflow is not valid JSON'); } }
    const result = await api('/api/ai/image', {method:'POST', body:JSON.stringify({
      provider, prompt, negative_prompt: negative, width:Number($('#imageWidth').value), height:Number($('#imageHeight').value),
      api_key: provider==='openai' ? state.settings.openaiKey : provider==='gemini' ? state.settings.geminiKey : '',
      model: provider==='openai' ? (state.settings.openaiModel||'gpt-image-2') : provider==='gemini' ? (state.settings.geminiModel||'gemini-3.1-flash-image') : '',
      comfy_url: state.settings.comfyUrl || 'http://127.0.0.1:8188', workflow,
      size: '1024x1536', quality:'high', aspect_ratio:'2:3', image_size:'2K'
    })});
    const imageExtra = state.selected.catalog_kind === 'official' ? {...(state.selected.extra || {}), official_image_category:'generated', official_portrait_path:result.image_path, official_image_filename:''} : (state.selected.extra || {});
    const saved = await updateEntry(state.selected.id, {...state.selected, image_path:result.image_path, extra:imageExtra}, false);
    state.selected = saved; $('#imagePreview').innerHTML = `<img src="${attr(result.image_path)}?t=${Date.now()}" alt="Generated portrait" />`;
    toast('Portrait attached to the codex entry.');
  } catch (e) { toast(`Image generation failed: ${e.message}`, 'error'); }
  finally { button.disabled = false; updateImageProviderText(); }
}
async function uploadLocalImage(file) {
  if (!file || !state.selected) return;
  const fd = new FormData(); fd.append('file', file);
  try {
    const result = await api('/api/media', {method:'POST', body:fd});
    const imageExtra = state.selected.catalog_kind === 'official' ? {...(state.selected.extra || {}), official_image_category:'user-attached', official_portrait_path:result.image_path, official_image_filename:''} : (state.selected.extra || {});
    const saved = await updateEntry(state.selected.id, {...state.selected, image_path:result.image_path, extra:imageExtra}, false); state.selected = saved;
    $('#imagePreview').innerHTML = `<img src="${attr(result.image_path)}?t=${Date.now()}" alt="Attached portrait" />`; toast('Local image attached.');
  } catch (e) { toast(e.message, 'error'); }
}

async function loadSettings() {
  try { state.settings = await api('/api/settings'); } catch { state.settings = {}; }
  if (state.settings.remoteOfficialImages === undefined) state.settings.remoteOfficialImages = false;
  const pairs = {openrouterKey:'openrouterKey', defaultImageProvider:'defaultImageProvider', openaiKey:'openaiKey', openaiModel:'openaiModel', geminiKey:'geminiKey', geminiModel:'geminiModel', comfyUrl:'comfyUrl', comfyWorkflow:'comfyWorkflow'};
  Object.entries(pairs).forEach(([id,key]) => { const el = $(`#${id}`); if (el) el.value = state.settings[key] ?? el.value; });
  $('#compactCards').checked = !!state.settings.compactCards;
  $('#remoteOfficialImages').checked = state.settings.remoteOfficialImages !== false;
  if (Array.isArray(state.settings.models)) { state.models = state.settings.models; renderModelSelects(); }
  renderEntries();
}
function readSettings() {
  return {
    ...state.settings,
    openrouterKey: $('#openrouterKey').value.trim(), openrouterModel: $('#openrouterModel').value,
    defaultImageProvider: $('#defaultImageProvider').value || 'comfyui',
    openaiKey: $('#openaiKey').value.trim(), openaiModel: $('#openaiModel').value.trim() || 'gpt-image-2',
    geminiKey: $('#geminiKey').value.trim(), geminiModel: $('#geminiModel').value.trim() || 'gemini-3.1-flash-image',
    comfyUrl: $('#comfyUrl').value.trim() || 'http://127.0.0.1:8188', comfyWorkflow: $('#comfyWorkflow').value.trim(),
    compactCards: $('#compactCards').checked, remoteOfficialImages: $('#remoteOfficialImages').checked, models: state.models,
  };
}
async function saveSettings(ev) {
  ev.preventDefault(); state.settings = readSettings();
  try { await api('/api/settings', {method:'PUT', body:JSON.stringify({settings:state.settings})}); els.settingsDialog.close(); renderEntries(); toast('Settings saved locally.'); } catch(e){toast(e.message,'error');}
}
async function fetchModels() {
  const key = $('#openrouterKey').value.trim(); if (!key) { toast('Enter your OpenRouter key first.', 'error'); return; }
  const btn = $('#fetchModelsBtn'); btn.disabled = true; btn.textContent = 'Fetching…';
  try { const data = await api('/api/openrouter/models', {method:'POST', body:JSON.stringify({api_key:key})}); state.models = data.models.sort((a,b)=>a.name.localeCompare(b.name)); renderModelSelects(); toast(`Loaded ${state.models.length} models.`); }
  catch(e){toast(e.message,'error');} finally {btn.disabled=false;btn.textContent='Fetch OpenRouter Models';}
}
function renderModelSelects() {
  const html = '<option value="">Choose a model</option>' + state.models.map(m=>`<option value="${attr(m.id)}">${esc(m.name)}</option>`).join('');
  $('#openrouterModel').innerHTML = html; $('#forgeModel').innerHTML = html;
  const selected = state.settings.openrouterModel || ''; $('#openrouterModel').value = selected; $('#forgeModel').value = selected;
}

async function cacheAllOfficial() {
  const btn = $('#cacheOfficialBtn'), status = $('#officialSyncStatus');
  btn.disabled = true; btn.textContent = 'Opening browser…';
  try {
    const launch = await api('/api/official/cache-browser-launch', {method:'POST'});
    status.textContent = `${launch.complete || launch.cached || 0} / ${launch.total || 237} entries fully indexed · ${launch.mugshots || 0} mugshots · ${launch.portraits || 0} portraits · ${launch.entry_images || 0} entry pages.`;
    toast(launch.started ? 'Real-browser cache launched. Complete any Cloudflare check in the opened browser.' : 'The real-browser cache is already running.');
    btn.textContent = 'Browser Cache Running…';
    while (true) {
      await new Promise(resolve => setTimeout(resolve, 1600));
      const info = await api('/api/official/cache-browser-status');
      const tail = (info.log_tail || []).slice(-1)[0] || '';
      status.textContent = `${info.complete || info.cached} / ${info.total} entries complete · ${info.mugshots || 0} mugshots · ${info.portraits || 0} portraits · ${info.entry_images || 0} entry pages${info.running ? ' · browser helper active' : ''}${tail ? ` · ${tail}` : ''}`;
      if (!info.running) {
        await loadEntries();
        if (info.exit_code === 0) toast(`Official media cache finished: ${info.assets || 0} local assets across ${info.complete || info.cached} complete entries.`);
        else toast(`Browser cache stopped with exit code ${info.exit_code}. See userdata/official-browser-cache.log.`, 'error');
        break;
      }
    }
  } catch (e) {
    toast(`Could not launch real-browser cache: ${e.message}`, 'error');
    status.textContent = `${e.message} You can also run cache_official_images_windows.bat.`;
  } finally {
    btn.disabled = false; btn.textContent = 'Open Real-Browser Cache';
  }
}

async function generateMissingArtBatch() {
  const btn = $('#generateMissingArtBtn'), status = $('#aiArtBatchStatus');
  const provider = $('#batchImageProvider').value || 'default';
  const kinds = ($('#batchImageKinds').value || 'ai').split(',');
  const limit = Math.max(1, Math.min(2000, Number($('#batchImageLimit').value) || 10));
  const resolved = provider === 'default' ? (state.settings.defaultImageProvider || 'comfyui') : provider;
  if (String(resolved).startsWith('manual-')) {
    toast('Batch generation cannot automate ChatGPT/Gemini subscription handoff. Choose ComfyUI, OpenAI API, or Gemini API.', 'error');
    return;
  }
  const hosted = ['openai','gemini'].includes(resolved);
  if (hosted && !confirm(`Generate up to ${limit} portraits with ${resolved.toUpperCase()} API? This can create billable API usage.`)) return;
  btn.disabled = true; btn.textContent = 'Starting batch…';
  try {
    state.settings = readSettings();
    await api('/api/settings', {method:'PUT', body:JSON.stringify({settings:state.settings})});
    const launch = await api('/api/ai/image-batch-launch', {method:'POST', body:JSON.stringify({
      provider, catalog_kinds:kinds, limit, refresh:false, confirm_hosted:hosted
    })});
    status.textContent = `${launch.with_images || 0} / ${launch.total || 0} entries currently illustrated · ${launch.missing || 0} missing.`;
    toast(launch.started ? 'Portrait batch started.' : 'A portrait batch is already running.');
    btn.textContent = 'Portrait Batch Running…';
    const kindQuery = encodeURIComponent(kinds.join(','));
    while (true) {
      await new Promise(resolve => setTimeout(resolve, 1800));
      const info = await api(`/api/ai/image-batch-status?catalog_kinds=${kindQuery}`);
      const tail = (info.log_tail || []).slice(-1)[0] || '';
      status.textContent = `${info.with_images || 0} / ${info.total || 0} illustrated · ${info.missing || 0} missing${info.running ? ' · generator active' : ''}${tail ? ` · ${tail}` : ''}`;
      if (!info.running) {
        await loadEntries();
        if (info.exit_code === 0) toast('Missing portrait batch finished.');
        else toast(`Portrait batch stopped with exit code ${info.exit_code}. See userdata/ai-image-generation.log.`, 'error');
        break;
      }
    }
  } catch (e) {
    toast(`Could not generate missing portraits: ${e.message}`, 'error');
    status.textContent = `${e.message} You can also run generate_missing_ai_images_windows.bat.`;
  } finally {
    btn.disabled = false; btn.textContent = 'Generate Missing Portraits';
  }
}

function openExport(id) { state.exportId = id; els.exportDialog.showModal(); }
function doExport(kind) {
  const id = state.exportId; if (!id) return;
  const paths = {json:`/api/export/ccv3/${id}.json`, png:`/api/export/ccv3/${id}.png`, charx:`/api/export/ccv3/${id}.charx`, lorebook:`/api/export/lorebook/${id}.json`};
  window.location.href = paths[kind]; els.exportDialog.close();
}

function showHelp(kind) {
  if (kind === 'silly') {
    $('#helpTitle').textContent = 'SillyTavern Bridge';
    $('#helpBody').innerHTML = `<h3>One entry, four portable forms</h3><ol><li>Open an entry and choose <b>Export</b>.</li><li>Use <b>CCv3 PNG</b> or <b>CHARX</b> for a portable character card with embedded codex lore.</li><li>Use <b>Lorebook JSON</b> when you want the species as World Info rather than a single roleplay character.</li><li>The exporter includes personality, scenario, first message, example dialogue, and a character-bound lorebook.</li></ol><p>Official reference records may have intentionally sparse roleplay fields until you add your own licensed notes or clone them into the User library.</p>`;
  } else {
    $('#helpTitle').textContent = 'ComfyUI Bridge';
    $('#helpBody').innerHTML = `<h3>API workflow setup</h3><ol><li>Enable Dev Mode in ComfyUI.</li><li>Build and test your preferred portrait workflow.</li><li>Choose <b>Save (API Format)</b>.</li><li>Paste that JSON into Settings → ComfyUI.</li><li>Replace prompt/seed/dimension values in the JSON with <code>{{PROMPT}}</code>, <code>{{NEGATIVE_PROMPT}}</code>, <code>{{WIDTH}}</code>, <code>{{HEIGHT}}</code>, and <code>{{SEED}}</code>.</li></ol><p>The app queues the workflow, polls its history, downloads the first output image, and attaches it to the codex entry.</p>`;
  }
  els.helpDialog.showModal();
}

async function importFile(file) {
  if (!file) return; const fd = new FormData(); fd.append('file', file); fd.append('mode','merge');
  try { const result = await api('/api/import/file', {method:'POST', body:fd}); toast(`Import: ${result.created} created, ${result.updated} updated, ${result.skipped} skipped.`); await loadEntries(); }
  catch(e){toast(e.message,'error');}
}

function setView(view) {
  state.currentView = view;
  try { localStorage.setItem('monstrum.lastView', view); } catch {}
  $$('.nav-item[data-view]').forEach(x=>x.classList.toggle('active', x.dataset.view === view));
  state.filters.favorites = view === 'favorites';
  state.filters.catalog_kind = ['official','ai','user'].includes(view) ? view : '';
  state.filters.sort = view === 'recent' ? 'newest' : 'name'; els.sort.value = state.filters.sort;
  const titles = {
    all:['The Infinite Index','Official references, AI-forged species, and your own creations in three clearly separated libraries.'],
    official:['Official Archive','Canonical Monster Girl Encyclopedia profile index with source-linked preview art.'],
    ai:['AI-Forged Bestiary','Built-in original archetypes and species created through OpenRouter.'],
    user:['User Creations','Your hand-authored species, imports, edits, and personal worldbuilding.'],
    favorites:['Favorites','Pinned specimens from every library.'],
    recent:['Recently Added','The newest and most recently revised records across the codex.'],
  };
  const copy = titles[view] || titles.all; $('#pageTitle').textContent = copy[0]; $('#pageSubtitle').textContent = copy[1];
  loadEntries();
}

function bindEvents() {
  $('#forgeBtn').addEventListener('click', () => els.forgeDialog.showModal()); $('#emptyForgeBtn').addEventListener('click', () => els.forgeDialog.showModal());
  $('#newUserBtn').addEventListener('click', () => openEditor({catalog_kind:'user', source_name:'User-created'}));
  $('#settingsBtn').addEventListener('click', () => els.settingsDialog.showModal());
  $('#homeBtn').addEventListener('click', () => { state.filters = {query:'',family:'',habitat:'',rarity:'',favorites:false,catalog_kind:'',sort:'name'}; els.search.value=''; setView('all'); });
  els.search.addEventListener('input', debounce(() => {state.filters.query=els.search.value;loadEntries();},220));
  [['family',els.family],['habitat',els.habitat],['rarity',els.rarity],['sort',els.sort]].forEach(([k,el])=>el.addEventListener('change',()=>{state.filters[k]=el.value;loadEntries();}));
  $('#clearFilters').addEventListener('click',()=>{state.filters.family=state.filters.habitat=state.filters.rarity='';els.family.value=els.habitat.value=els.rarity.value='';loadEntries();});
  $$('.nav-item[data-view]').forEach(btn => btn.addEventListener('click', () => setView(btn.dataset.view)));
  $('#closeDetail').addEventListener('click', closeDetail); els.veil.addEventListener('click', closeDetail);
  $('#favoriteDetail').addEventListener('click', async ev => {
    if (!state.selected) return;
    if (!state.selected.favorite) {
      const r = ev.currentTarget.getBoundingClientRect();
      heartBurst(r.left + r.width / 2, r.top + r.height / 2);
    }
    await updateEntry(state.selected.id, {...state.selected, favorite: !state.selected.favorite});
  });
  $('#editDetail').addEventListener('click',()=>{if(!state.selected)return;if(state.selected.catalog_kind==='official'){cloneOfficialEntry(state.selected);}else{closeDetail();openEditor(state.selected);}}); $('#exportDetail').addEventListener('click',()=>state.selected&&openExport(state.selected.id));
  $('#forgeForm').addEventListener('submit', runForge); $('#editorForm').addEventListener('submit', saveEditor); $('#imageForm').addEventListener('submit', runImage); $('#settingsForm').addEventListener('submit', saveSettings);
  $('#deleteEntry').addEventListener('click',async()=>{if(!state.editingId||!confirm('Delete this codex entry?'))return;try{await api(`/api/entries/${state.editingId}`,{method:'DELETE'});els.editorDialog.close();closeDetail();await loadEntries();toast('Entry deleted.');}catch(e){toast(e.message,'error');}});
  $('#imageProvider').addEventListener('change', updateImageProviderText); $('#localImageInput').addEventListener('change',e=>uploadLocalImage(e.target.files[0]));
  $('#fetchModelsBtn').addEventListener('click', fetchModels); $('#cacheOfficialBtn').addEventListener('click', cacheAllOfficial); $('#generateMissingArtBtn').addEventListener('click', generateMissingArtBatch);
  $$('.settings-tabs button').forEach(btn=>btn.addEventListener('click',()=>{$$('.settings-tabs button').forEach(x=>x.classList.remove('active'));$$('.settings-pane').forEach(x=>x.classList.remove('active'));btn.classList.add('active');$(`[data-pane="${btn.dataset.tab}"]`).classList.add('active');}));
  $('#backupBtn').addEventListener('click',()=>location.href='/api/export/codex.json'); $('#settingsBackupBtn').addEventListener('click',()=>location.href='/api/export/codex.json');
  $('#importBtn').addEventListener('click',()=>$('#importFile').click()); $('#importFile').addEventListener('change',e=>importFile(e.target.files[0]));
  $('#openSillyHelp').addEventListener('click',()=>showHelp('silly')); $('#openComfyHelp').addEventListener('click',()=>showHelp('comfy')); $('#closeHelp').addEventListener('click',()=>els.helpDialog.close());
  $('#closeExport').addEventListener('click',()=>els.exportDialog.close()); $$('.export-grid button').forEach(btn=>btn.addEventListener('click',()=>doExport(btn.dataset.export)));
  $('#closeOfficialMedia').addEventListener('click',()=>$('#officialMediaDialog').close()); $('#closeOfficialMediaFooter').addEventListener('click',()=>$('#officialMediaDialog').close());
  $('#surpriseBtn').addEventListener('click', surpriseMe);
  bindCardTilt();
  $('#cheatBtn').addEventListener('click', () => $('#cheatDialog').showModal());
  $('#closeCheat').addEventListener('click', () => $('#cheatDialog').close());
  $('#prevEntryBtn').addEventListener('click', () => navEntry(-1));
  $('#nextEntryBtn').addEventListener('click', () => navEntry(1));
  document.addEventListener('keydown', e => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (document.querySelector('dialog[open]')) return;
    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.target.isContentEditable) return;
    const key = e.key.toLowerCase();
    if (els.panel.classList.contains('open')) {
      if (key === 'arrowleft') { e.preventDefault(); navEntry(-1); }
      else if (key === 'arrowright') { e.preventDefault(); navEntry(1); }
      else if (key === 'f') { e.preventDefault(); if (state.selected) updateEntry(state.selected.id, {...state.selected, favorite: !state.selected.favorite}); }
    }
    if (key === 's') { e.preventDefault(); surpriseMe(); }
    else if (key === '?' || (e.shiftKey && key === '/')) { e.preventDefault(); $('#cheatDialog').showModal(); }
  });
  document.addEventListener('keydown', e => { if ((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();els.search.focus();} if(e.key==='Escape'&&els.panel.classList.contains('open'))closeDetail(); });
}

/* =====================================================================
   v1.3.0 Living Codex — habitat ambience engine, navigation, polish
   ===================================================================== */

const SCENES = {
  ember:    { glyph: '✵', colors: ['#ffb066', '#ff7a45', '#ffd98a'], mode: 'rise',    speed: 1.0, size: [1.6, 4.6], alpha: [.35, .95], glow: true  },
  snow:     { glyph: '❄', colors: ['#eef6ff', '#cfe6ff'],           mode: 'fall',    speed: .8,  size: [1.2, 3.6], alpha: [.3, .8],  glow: false },
  sea:      { glyph: '≈', colors: ['#58d6ef', '#8fe3ff', '#bff2ff'], mode: 'rise',    speed: .7,  size: [1.5, 5.0], alpha: [.2, .65], glow: true, wobble: true },
  desert:   { glyph: '☼', colors: ['#f0c36c', '#e8b45a', '#d9a349'], mode: 'drift',   speed: .35, size: [1.0, 3.4], alpha: [.15, .5],  glow: false },
  forest:   { glyph: '❦', colors: ['#9fe87a', '#d8f2a0', '#7ad9a2'], mode: 'float',   speed: .5,  size: [1.0, 2.8], alpha: [.3, .8],  glow: true, wander: true },
  swamp:    { glyph: 'Ϟ', colors: ['#66d69e', '#a4e08a', '#cfe8a0'], mode: 'float',   speed: .4,  size: [1.4, 3.2], alpha: [.25, .6],  glow: true, wander: true },
  cave:     { glyph: '✦', colors: ['#9fd8ff', '#e0f2ff', '#c0a8ff'], mode: 'twinkle', speed: .3,  size: [.9, 2.6],  alpha: [.25, .9],  glow: true  },
  city:     { glyph: '⌂', colors: ['#f0c36c', '#ffd98a', '#e8b45a'], mode: 'drift',   speed: .3,  size: [1.0, 3.0], alpha: [.15, .5],  glow: false },
  cosmic:   { glyph: '✧', colors: ['#c8d8ff', '#ffffff', '#a8c8ff'], mode: 'twinkle', speed: .4,  size: [.8, 2.4],  alpha: [.3, .95],  glow: true  },
  spectral: { glyph: '☽', colors: ['#b9a8ff', '#d8ccff', '#8fd8c8'], mode: 'wisp',    speed: .45, size: [1.2, 4.0], alpha: [.2, .6],   glow: true, wander: true },
  plains:   { glyph: '❀', colors: ['#d8f2a0', '#ffe3a1', '#bff3d6'], mode: 'drift',   speed: .35, size: [1.0, 3.0], alpha: [.18, .5],  glow: false },
  infernal: { glyph: '✵', colors: ['#ff5878', '#ff8a5c', '#ffb066'], mode: 'rise',    speed: 1.2, size: [1.6, 4.6], alpha: [.35, .9],  glow: true  },
  default:  { glyph: '·', colors: ['#9d94aa', '#c9c0fb', '#8468ff'], mode: 'drift',   speed: .25, size: [1.0, 2.8], alpha: [.15, .45], glow: false },
};
const SCENE_RULES = [
  [/(volcan|lava|sulfur|sulphur|ember|inferno|molten|magma|basalt)/i, 'ember'],
  [/(snow|winter|frost|glacier|ice|frozen|alpine|mountain|crag|peak|highland|loch)/i, 'snow'],
  [/(forest|grove|tree|wood|orchard|jungle|willow|timber|thicket|banana)/i, 'forest'],
  [/(sea|ocean|coast|beach|island|shore|wave|tide|whirlpool|strait|reef|aqua|water|river|lake|stream|cyclone|storm)/i, 'sea'],
  [/(swamp|marsh|flood|fen|bog|mire|rain)/i, 'swamp'],
  [/(desert|dune|sand|mesa|canyon|oasis|salt|arid|tomb|crypt|necropol)/i, 'desert'],
  [/(cave|cavern|underground|deep|mine|tunnel|subterra)/i, 'cave'],
  [/(city|market|temple|estate|road|inn|hall|loom|quarter|village|town|home|hearth|house|palace|castle|bridge|ruin|sanctuary|crossroads)/i, 'city'],
  [/(cosmic|star|void|space|moon|celestial|nebula|galaxy|orbit|astral)/i, 'cosmic'],
  [/(spectr|ghost|spirit|phantom|haunt|wraith|wisp|soul|banshee)/i, 'spectral'],
  [/(meadow|field|plain|steppe|prairie|flower|garden|petal|grass)/i, 'plains'],
  [/(infernal|hell|demon|abyss|fiend|shadow|dark)/i, 'infernal'],
];
function livingSceneType(habitat = '') {
  const h = String(habitat || '').trim();
  if (!h) return null;
  for (const [re, type] of SCENE_RULES) if (re.test(h)) return type;
  return 'default';
}
/* Species-name archetype rules — used when an entry has no real habitat data
   (Official index records carry the "See official profile" placeholder). */
const NAME_RULES = [
  [/(yuki|snow|frost|ice|glacier|winter|blizzard|hail)/i, 'snow'],
  [/(mermaid|siren|nereid|merrow|undine|nixie|kelpie|jellyfish|mizu|sea|ocean|wave|lake|river|pond|water)/i, 'sea'],
  [/(alraune|dryad|flower|rose|vine|briar|bloom|sprout|shroom|mushroom|fungus|plant|treant|leaf|forest|wood)/i, 'forest'],
  [/(salamander|volcano|lava|ember|flame|fire|phoenix|molten|magma|forge)/i, 'ember'],
  [/(ghost|wraith|banshee|spectre|specter|poltergeist|phantom|wisp|shade|haunt|soul|lich|ghoul|reaper)/i, 'spectral'],
  [/(slime|frog|toad|marsh|swamp|bog)/i, 'swamp'],
  [/(sand|desert|dune|cactus|mummy|sphinx|anubis|tomb|scarab)/i, 'desert'],
  [/(arachne|spider|scorpion|goblin|dwarf|mine|cavern|cave|troglodyte|beetle|hive)/i, 'cave'],
  [/(angel|seraph|cherub|celestial|cosmic|star|moon|astral|galaxy|nebula|void|space)/i, 'cosmic'],
  [/(demon|oni|devil|fiend|hell|imp|succubus|incubus|fallen|dark)/i, 'infernal'],
  [/(centaur|unicorn|pegasus|harpy|horse|mare|steed|rocinante|pixie|fairy|sylph)/i, 'plains'],
  [/(gryphon|griffin|dragon|wyvern|roc|eagle|owl|raven|crow|vulture)/i, 'snow'],
  [/(domovoi|house|brownie|doll|maid|servant|spirit|estate|mansion)/i, 'city'],
];
function livingSceneFor(entry = {}) {
  const habitat = String(entry.habitat || '').trim();
  if (habitat && !/see official profile/i.test(habitat)) {
    const t = livingSceneType(habitat);
    if (t) return t;
  }
  for (const field of ['ecology', 'lore', 'appearance']) {
    const t = livingSceneType(String(entry[field] || ''));
    if (t) return t;
  }
  const family = String(entry.family || '').trim();
  if (family && !/official/i.test(family)) {
    const t = livingSceneType(family);
    if (t) return t;
  }
  const name = String(entry.name || '').trim();
  for (const [re, type] of NAME_RULES) if (re.test(name)) return type;
  return 'default';
}
function sceneGlyph(entry = {}) {
  const type = livingSceneFor(entry);
  return type && type !== 'default' ? SCENES[type].glyph : '';
}

/* Search term highlighting (escapes first, then wraps matches in <mark>) */
function hl(text = '') {
  const safe = esc(text);
  const q = (state.filters?.query || '').trim();
  if (!q) return safe;
  try {
    const re = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
    return safe.replace(re, m => `<mark>${m}</mark>`);
  } catch { return safe; }
}

/* Hero specimen counter counts up instead of snapping */
let countRaf = 0;
function animateCount(el, target) {
  cancelAnimationFrame(countRaf);
  const from = Number((el.textContent || '').replace(/[^\d]/g, '')) || 0;
  if (from === target) { el.textContent = target.toLocaleString(); return; }
  const start = performance.now(), dur = 620;
  const step = now => {
    const t = Math.min(1, (now - start) / dur);
    const eased = 1 - Math.pow(1 - t, 3);
    el.textContent = Math.round(from + (target - from) * eased).toLocaleString();
    if (t < 1) countRaf = requestAnimationFrame(step);
  };
  countRaf = requestAnimationFrame(step);
}

/* Surprise me — a random specimen from the current view */
async function surpriseMe() {
  const glyph = $('.surprise-glyph', $('#surpriseBtn'));
  if (glyph) { glyph.classList.remove('surprise-flash'); void glyph.offsetWidth; glyph.classList.add('surprise-flash'); }
  if (!state.entries.length) await loadEntries();
  if (!state.entries.length) { toast('The codex is empty.', 'error'); return; }
  const entry = state.entries[Math.floor(Math.random() * state.entries.length)];
  closeDetail();
  await openDetail(entry.id);
  toast(`The codex yields: ${entry.name}`);
}

/* Prev/next through the current filtered view */
function navEntry(dir) {
  if (!state.selected) return;
  const idx = state.entries.findIndex(x => x.id === state.selected.id);
  const next = idx + dir;
  if (idx === -1 || next < 0 || next >= state.entries.length) return;
  openDetail(state.entries[next].id);
}
function setNavState() {
  const idx = state.selected ? state.entries.findIndex(x => x.id === state.selected.id) : -1;
  $('#prevEntryBtn').disabled = idx <= 0;
  $('#nextEntryBtn').disabled = idx === -1 || idx >= state.entries.length - 1;
}

/* ---- v1.4.0 interactions ------------------------------------------- */
/* Recently viewed chips (localStorage, last 8) */
function pushRecent(entry) {
  if (!entry || typeof entry.id !== 'number') return;
  let ids = [];
  try { ids = JSON.parse(localStorage.getItem('monstrum.recent') || '[]'); } catch {}
  ids = [entry.id, ...ids.filter(x => x !== entry.id)].slice(0, 8);
  try { localStorage.setItem('monstrum.recent', JSON.stringify(ids)); } catch {}
}
function renderRecent() {
  const strip = $('#recentStrip');
  if (!strip) return;
  let ids = [];
  try { ids = JSON.parse(localStorage.getItem('monstrum.recent') || '[]'); } catch {}
  const items = ids.map(id => state.entries.find(en => en.id === id)).filter(Boolean).slice(0, 8);
  strip.innerHTML = items.length ? `<span class="recent-label">Recently viewed</span>` + items.map(entry => {
    const assets = imageAssetCandidates(entry);
    const thumb = assets.length ? `<img src="${attr(assets[0].src)}" alt="" loading="lazy" />` : `<span class="recent-rune">${esc(initials(entry.name))}</span>`;
    return `<button type="button" class="recent-chip" data-id="${entry.id}" title="${attr(entry.name)}">${thumb}<span>${esc(entry.name)}</span><span class="recent-x">×</span></button>`;
  }).join('') : '';
  $$('.recent-chip', strip).forEach(chip => chip.addEventListener('click', () => openDetail(Number(chip.dataset.id))));
}

/* Favorite heart-burst sparks */
function heartBurst(x, y) {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  for (let i = 0; i < 7; i++) {
    const s = document.createElement('span');
    s.className = 'fav-burst';
    s.textContent = i % 3 === 0 ? '♥' : i % 3 === 1 ? '✦' : '♡';
    const ang = (-90 + (i - 3) * 26 + (Math.random() * 14 - 7)) * Math.PI / 180;
    const dist = 42 + Math.random() * 46;
    s.style.left = `${x}px`;
    s.style.top = `${y}px`;
    s.style.setProperty('--bx', `${Math.cos(ang) * dist}px`);
    s.style.setProperty('--by', `${Math.sin(ang) * dist}px`);
    s.style.setProperty('--br', `${Math.random() * 40 - 20}deg`);
    s.style.animationDelay = `${i * 28}ms`;
    document.body.appendChild(s);
    setTimeout(() => s.remove(), 1150 + i * 28);
  }
}

/* Card tilt: one delegated, rAF-throttled listener for the whole grid */
function bindCardTilt() {
  if (!window.matchMedia('(pointer: fine)').matches) return;
  let tiltRaf = 0;
  els.grid.addEventListener('pointermove', ev => {
    if (tiltRaf) return;
    tiltRaf = requestAnimationFrame(() => {
      tiltRaf = 0;
      const card = ev.target.closest ? ev.target.closest('.specimen-card') : null;
      $$('.tilting', els.grid).forEach(c => { if (c !== card) { c.classList.remove('tilting'); c.style.transform = ''; } });
      if (!card || document.body.classList.contains('compact')) return;
      card.classList.add('tilting');
      const r = card.getBoundingClientRect();
      const px = (ev.clientX - r.left) / r.width - .5;
      const py = (ev.clientY - r.top) / r.height - .5;
      card.style.transform = `perspective(760px) rotateY(${(px * 6).toFixed(2)}deg) rotateX(${(py * -5).toFixed(2)}deg) translateY(-2px)`;
    });
  });
  els.grid.addEventListener('pointerleave', () => {
    if (tiltRaf) { cancelAnimationFrame(tiltRaf); tiltRaf = 0; }
    $$('.tilting', els.grid).forEach(c => { c.classList.remove('tilting'); c.style.transform = ''; });
  });
}

/* ---- Living habitat scene engine ----------------------------------- */
const sceneEngines = new Map();
let sceneObserver = null;

function bootScenes(root = document) {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  $$('canvas.living-scene:not([data-scene-ready])', root).forEach(initSceneCanvas);
}
function initSceneCanvas(canvas) {
  if (sceneEngines.has(canvas)) return;
  canvas.setAttribute('data-scene-ready', '1');
  const cfg = SCENES[canvas.dataset.scene] || SCENES.default;
  const hero = canvas.closest('.detail-hero') !== null;
  const danger = Number(canvas.closest('[data-danger]')?.dataset.danger) || 0;
  const engine = createSceneEngine(canvas, cfg, hero, danger);
  if (!engine) return;
  sceneEngines.set(canvas, engine);
  if (!sceneObserver) {
    sceneObserver = new IntersectionObserver(entries => entries.forEach(en => {
      const eng = sceneEngines.get(en.target);
      if (eng) eng.setPaused(!en.isIntersecting);
    }), { rootMargin: '140px' });
  }
  sceneObserver.observe(canvas);
}

function createSceneEngine(canvas, cfg, hero, danger = 0) {
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const sprites = new Map();
  let w = 0, h = 0, raf = 0, particles = [], paused = false;
  /* Danger-reactive ambience: deadlier specimens burn brighter and faster */
  const heatMul = 1 + Math.min(2, Math.max(0, Number(danger) || 0)) * 0.22;

  const sprite = color => {
    let s = sprites.get(color);
    if (s) return s;
    s = document.createElement('canvas');
    s.width = s.height = 32;
    const c = s.getContext('2d');
    const g = c.createRadialGradient(16, 16, 0, 16, 16, 16);
    g.addColorStop(0, 'rgba(255,255,255,.9)');
    g.addColorStop(.28, color);
    g.addColorStop(1, 'rgba(0,0,0,0)');
    c.fillStyle = g;
    c.fillRect(0, 0, 32, 32);
    sprites.set(color, s);
    return s;
  };

  const resize = () => {
    const rect = canvas.getBoundingClientRect();
    w = Math.max(1, rect.width);
    h = Math.max(1, rect.height);
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  };

  const make = () => ({
    x: Math.random() * w,
    y: Math.random() * h,
    size: cfg.size[0] + Math.random() * (cfg.size[1] - cfg.size[0]),
    color: cfg.colors[(Math.random() * cfg.colors.length) | 0],
    alpha: cfg.alpha[0] + Math.random() * (cfg.alpha[1] - cfg.alpha[0]),
    phase: Math.random() * Math.PI * 2,
    speed: (0.35 + Math.random() * 0.65) * cfg.speed * (hero ? 0.85 : 1),
    vx: (Math.random() - .5) * .3,
    vy: (Math.random() - .5) * .3,
    wander: .4 + Math.random() * .9,
  });

  const count = Math.max(4, Math.round((hero ? 46 : 12) * heatMul * Math.min(1.6, (w * h) / (hero ? 240000 : 90000))));
  const reset = () => { resize(); particles = Array.from({ length: count }, make); };

  const step = now => {
    if (!canvas.isConnected) {
      cancelAnimationFrame(raf);
      sceneEngines.delete(canvas);
      sceneObserver?.unobserve(canvas);
      return;
    }
    if (paused || document.hidden) return;
    ctx.clearRect(0, 0, w, h);
    const t = now / 1000;
    const wobble = cfg.wobble ? .8 : .35;
    for (const p of particles) {
      switch (cfg.mode) {
        case 'rise':
          p.y -= p.speed * 1.15;
          p.x += Math.sin(t * p.wander + p.phase) * wobble;
          if (p.y < -24) { p.y = h + 24; p.x = Math.random() * w; }
          break;
        case 'fall':
          p.y += p.speed * 1.15;
          p.x += Math.sin(t * p.wander + p.phase) * .4;
          if (p.y > h + 24) { p.y = -24; p.x = Math.random() * w; }
          break;
        case 'drift':
          p.x += p.vx * p.speed;
          p.y += p.vy * p.speed;
          p.vx += (Math.random() - .5) * .008;
          p.vy += (Math.random() - .5) * .008;
          p.vx = Math.max(-.6, Math.min(.6, p.vx));
          p.vy = Math.max(-.6, Math.min(.6, p.vy));
          if (p.x < -24) p.x = w + 24; else if (p.x > w + 24) p.x = -24;
          if (p.y < -24) p.y = h + 24; else if (p.y > h + 24) p.y = -24;
          break;
        case 'float':
          p.x += p.vx * p.speed * .6 + Math.sin(t * p.wander + p.phase) * wobble;
          p.y += p.vy * p.speed * .6 + Math.cos(t * p.wander * .8 + p.phase) * .3;
          if (p.x < -24) p.x = w + 24; else if (p.x > w + 24) p.x = -24;
          if (p.y < -24) p.y = h + 24; else if (p.y > h + 24) p.y = -24;
          break;
        case 'twinkle':
          p.x += p.vx * p.speed * .2;
          p.y += p.vy * p.speed * .2;
          if (p.x < -24) p.x = w + 24; else if (p.x > w + 24) p.x = -24;
          if (p.y < -24) p.y = h + 24; else if (p.y > h + 24) p.y = -24;
          break;
        case 'wisp':
          p.x += Math.sin(t * p.wander * .6 + p.phase) * .5;
          p.y += Math.cos(t * p.wander * .45 + p.phase * 1.7) * .4 - p.speed * .25;
          if (p.y < -40) { p.y = h + 40; p.x = Math.random() * w; }
          break;
      }
      if (p.x < -24) p.x = w + 24; else if (p.x > w + 24) p.x = -24;
      const twinkle = cfg.mode === 'twinkle'
        ? .35 + .65 * (.5 + .5 * Math.sin(t * 2.2 * heatMul + p.phase))
        : .75 + .25 * Math.sin(t * 1.6 * heatMul + p.phase);
      const a = Math.max(0, Math.min(1, p.alpha * twinkle));
      if (a < .02) continue;
      const scale = 1 + (cfg.glow ? .18 * Math.sin(t * 2 + p.phase) : 0);
      const s = p.size * (cfg.glow ? 5 : 3.4) * scale;
      ctx.globalAlpha = a;
      ctx.drawImage(sprite(p.color), p.x - s / 2, p.y - s / 2, s, s);
    }
    ctx.globalAlpha = 1;
  };

  const loop = now => {
    raf = requestAnimationFrame(loop);
    if (!canvas.isConnected) {
      cancelAnimationFrame(raf);
      sceneEngines.delete(canvas);
      sceneObserver?.unobserve(canvas);
      return;
    }
    if (paused || document.hidden) return;
    step(now);
  };

  reset();
  raf = requestAnimationFrame(loop);
  window.addEventListener('resize', reset);
  return { setPaused: value => { paused = value; if (!paused) reset(); } };
}

/* Attach a living scene + drifting mist (+ pointer parallax) to the hero */
function attachHeroScene(hero, entry) {
  const type = livingSceneFor(entry);
  if (!type) return;
  const cfg = SCENES[type];
  const canvas = document.createElement('canvas');
  canvas.className = 'living-scene';
  canvas.dataset.scene = type;
  canvas.setAttribute('aria-hidden', 'true');
  const mistA = document.createElement('div');
  mistA.className = 'hero-mist mist-a';
  const mistB = document.createElement('div');
  mistB.className = 'hero-mist mist-b';
  hero.style.setProperty('--mist-a', cfg.colors[0]);
  hero.style.setProperty('--mist-b', cfg.colors[1] || cfg.colors[0]);
  hero.insertBefore(mistB, hero.firstChild);
  hero.insertBefore(mistA, hero.firstChild);
  hero.insertBefore(canvas, hero.firstChild);
  bootScenes(hero);
  /* Pointer parallax: art, particles and mist drift on their own depth */
  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches && window.matchMedia('(pointer: fine)').matches && !hero.dataset.parallax) {
    hero.dataset.parallax = '1';
    let rafId = 0;
    hero.addEventListener('pointermove', ev => {
      if (rafId) return;
      rafId = requestAnimationFrame(() => {
        rafId = 0;
        if (!canvas.isConnected) return;
        const r = hero.getBoundingClientRect();
        const nx = (ev.clientX - r.left) / Math.max(1, r.width) - .5;
        const ny = (ev.clientY - r.top) / Math.max(1, r.height) - .5;
        hero.style.setProperty('--parallax-x', `${(nx * 10).toFixed(2)}px`);
        hero.style.setProperty('--parallax-y', `${(ny * 7).toFixed(2)}px`);
      });
    });
    hero.addEventListener('pointerleave', () => {
      hero.style.setProperty('--parallax-x', '0px');
      hero.style.setProperty('--parallax-y', '0px');
    });
  }
}

async function boot() {
  bindEvents(); await loadSettings();
  let initialView = 'official';
  try { initialView = localStorage.getItem('monstrum.lastView') || 'official'; } catch {}
  if (!['all','official','ai','user','favorites','recent'].includes(initialView)) initialView = 'official';
  setView(initialView);
  try { const h=await api('/api/health'); $('#versionText').textContent=`v${h.version}`; } catch {}
}
boot();

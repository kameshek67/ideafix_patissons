/* Поступай по олимпиаде — SPA на чистом JS.
   Вся конкретика выводится таблицами (сортировка, фильтр, CSV).
   Текстом остаются только общие правила вуза, у которых нет названий олимпиад. */

const API = window.API_BASE || '';

const state = {
  tab: 'uni',
  benefitType: 'Все',
  universities: [],
  university: null,
  program: null,
  programData: null,
  olympiad: null,
  profileId: null,
  olympiadData: null,       // выдача по олимпиаде: список вузов
  pickedUniversity: null,   // вуз, выбранный внутри выдачи
  universityData: null,     // льготы выбранного вуза
  query: '',
  tables: {},
};

const TYPES = ['Все', 'БВИ', '100 баллов'];

const TYPE_STYLE = {
  'БВИ': { badge: 'badge-bvi', section: 'section-bvi', title: 'БВИ — без вступительных испытаний' },
  '100 баллов': { badge: 'badge-sto', section: 'section-sto', title: '100 баллов за ЕГЭ / ДВИ' },
  'Особое право (БВИ/100)': { badge: 'badge-alt', section: 'section-alt', title: 'Особое право: БВИ или 100 баллов' },
  'Фаст-трек': { badge: 'badge-alt', section: 'section-alt', title: 'Фаст-трек грантового конкурса' },
  'ИД (доп. баллы)': { badge: 'badge-alt', section: 'section-alt', title: 'Индивидуальные достижения' },
};

// ---------------------------------------------------------------- утилиты
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function plural(n, one, few, many) {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b > 1 && b < 5) return few;
  if (b === 1) return one;
  return many;
}

const fmt = n => new Intl.NumberFormat('ru-RU').format(n || 0);
const place = u => u.city || u.region || '';

async function api(path) {
  const res = await fetch(API + path);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

function debounce(fn, ms) {
  let t; return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

function emptyState(icon, title, text) {
  return `<div class="empty-state"><div class="empty-icon" aria-hidden="true">${icon}</div>
    <p class="empty-title">${esc(title)}</p>
    <p class="empty-text">${esc(text)}</p></div>`;
}

const SKELETON = `<div class="skeleton-stack">
  <div class="skeleton h-28 rounded-[15px]"></div><div class="skeleton h-64 rounded-[15px]"></div></div>`;

const ICON_DOWNLOAD = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
  stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>`;
const ICON_CHEVRON_RIGHT = `<svg class="uni-row-arrow" width="9" height="15" viewBox="0 0 9 15" fill="none" aria-hidden="true">
  <path d="M1 1l6.5 6.5L1 14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>`;
const ICON_CHEVRON_LEFT = `<svg width="8" height="13" viewBox="0 0 9 15" fill="none" aria-hidden="true">
  <path d="M8 1L1.5 7.5 8 14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>`;

// стартовые экраны из макета: подпись + 3D-иллюстрация
const ILLU = {
  uni: ['./assets/illu-uni.png', 305, 319],
  olymp: ['./assets/illu-olymp.png', 214, 232],
};
function illuState(kind, text) {
  const [src, w, h] = ILLU[kind];
  return `<div class="illu-state"><p>${esc(text)}</p><img src="${src}" alt="" width="${w}" height="${h}"></div>`;
}
const UNI_START = 'Выбери вуз и направление — получи таблицу льгот по олимпиадам';
const OLYMP_START = 'Введи название олимпиады. Выбери вуз из списка — получи таблицу льгот';

// ---------------------------------------------------------------- таблицы
const MAX_TABLE_ROWS = 400;

function tableState(id) {
  if (!state.tables[id]) state.tables[id] = { sort: null, dir: 1, filter: '' };
  return state.tables[id];
}

const cellText = (col, row) => col.text ? col.text(row) : String(row[col.key] ?? '');

function applyTableState(id, columns, rows) {
  const st = tableState(id);
  let out = rows;
  if (st.filter) {
    const needle = st.filter.toLowerCase();
    out = out.filter(row => columns.some(col => cellText(col, row).toLowerCase().includes(needle)));
  }
  if (st.sort !== null) {
    const col = columns[st.sort];
    out = [...out].sort((a, b) =>
      cellText(col, a).localeCompare(cellText(col, b), 'ru', { numeric: true }) * st.dir);
  }
  return out;
}

function renderTable(id, columns, rows, opts = {}) {
  const st = tableState(id);
  const matched = applyTableState(id, columns, rows);
  const visible = matched.slice(0, MAX_TABLE_ROWS);
  const head = columns.map((col, i) => `
    <th class="${col.hide === 'sm' ? 'hidden sm:table-cell' : ''} ${col.width || ''}" data-sort="${i}"
        title="${esc(col.title)} — сортировать">
      ${esc(col.title)}<span class="sort-mark">${st.sort === i ? (st.dir > 0 ? '▲' : '▼') : ''}</span>
    </th>`).join('');
  const body = visible.length ? visible.map(row => `
    <tr>${columns.map(col => `
      <td class="${col.hide === 'sm' ? 'hidden sm:table-cell' : ''}">${col.cell ? col.cell(row) : esc(row[col.key] ?? '')}</td>`).join('')}
    </tr>`).join('') : `<tr><td colspan="${columns.length}" class="py-6 text-center text-slate-400">Ничего не найдено</td></tr>`;

  return `
    <div class="table-wrap" data-table="${id}">
      <div class="table-toolbar">
        <input class="table-filter" placeholder="${esc(opts.placeholder || 'Фильтр…')}" value="${esc(st.filter)}">
        <span class="table-count">${fmt(matched.length)} из ${fmt(rows.length)}</span>
        <button class="chip chip-ghost ml-auto" data-csv="${id}" title="Скачать таблицу в CSV">${ICON_DOWNLOAD} CSV</button>
      </div>
      <div class="table-scroll">
        <table class="data-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>
      </div>
      ${matched.length > MAX_TABLE_ROWS ? `<p class="table-note">
        Показаны первые ${fmt(MAX_TABLE_ROWS)} строк из ${fmt(matched.length)} — уточните фильтр или выгрузите CSV.</p>` : ''}
    </div>`;
}

function bindTable(root, id, columns, rows, rerender) {
  const wrap = $(`[data-table="${id}"]`, root);
  if (!wrap) return;
  const st = tableState(id);

  $$('th[data-sort]', wrap).forEach(th => th.onclick = () => {
    const i = +th.dataset.sort;
    if (st.sort === i) st.dir = -st.dir; else { st.sort = i; st.dir = 1; }
    rerender();
  });

  const filter = $('.table-filter', wrap);
  filter.oninput = debounce(() => {
    st.filter = filter.value.trim();
    rerender();
    const again = $(`[data-table="${id}"] .table-filter`);
    if (again) { again.focus(); again.setSelectionRange(again.value.length, again.value.length); }
  }, 200);

  $('[data-csv]', wrap).onclick = () => exportCsv(id, columns, applyTableState(id, columns, rows));
}

function exportCsv(id, columns, rows) {
  const quote = v => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const lines = [columns.map(c => quote(c.title)).join(';')];
  rows.forEach(row => lines.push(columns.map(col => quote(cellText(col, row))).join(';')));
  const blob = new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${id}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

const clamp2 = value => `<span class="cell-clamp-2" title="${esc(value)}">${esc(value)}</span>`;
const dash = value => value || '—';

// колонки: направление -> олимпиады
const derivedMark = r => r.derived
  ? ` <span class="badge badge-soft" title="Строка выведена из правила вуза «любая олимпиада перечня с этим профилем»">по профилю</span>`
  : '';

const PROGRAM_COLUMNS = [
  { key: 'olympiad', title: 'Олимпиада', width: 'w-[26%]',
    cell: r => (r.olympiad_id
      ? `<button class="link-cell" data-olympiad="${r.olympiad_id}" data-name="${esc(r.olympiad)}">${esc(r.olympiad)}</button>`
      : esc(r.olympiad)) + derivedMark(r) },
  { key: 'profile', title: 'Профиль олимпиады', width: 'w-[22%]', cell: r => clamp2(r.profile) },
  { key: 'level', title: 'Ур.', width: 'w-[6%]' },
  { key: 'role', title: 'Кому', width: 'w-[13%]', hide: 'sm' },
  { key: 'grade', title: 'Класс', width: 'w-[9%]', hide: 'sm',
    cell: r => `<span class="nowrap">${esc(r.grade)}</span>` },
  { key: 'confirm', title: 'Подтверждение ЕГЭ', width: 'w-[15%]', hide: 'sm' },
  { key: 'min_ege', title: 'Балл', width: 'w-[9%]',
    cell: r => `<span class="nowrap">${esc(r.min_ege)}</span>` },
];

// колонки: олимпиада -> направления выбранного вуза
const UNIVERSITY_COLUMNS = [
  { key: 'program', title: 'Направление', width: 'w-[30%]',
    cell: r => `<button class="link-cell" data-program="${r.program_id}">${esc(r.program)}</button>
                ${r.program_profile ? `<div class="mt-0.5 text-[11.5px] meta-text cell-clamp-1"
                   title="${esc(r.program_profile)}">${esc(r.program_profile)}</div>` : ''}` },
  { key: 'code', title: 'Код', width: 'w-[9%]', hide: 'sm', cell: r => clamp2(r.code) },
  { key: 'type', title: 'Льгота', width: 'w-[11%]',
    cell: r => `<span class="badge ${TYPE_STYLE[r.type]?.badge || 'badge-soft'}">${esc(r.type)}</span>${derivedMark(r)}` },
  { key: 'profile', title: 'Профиль олимпиады', width: 'w-[20%]', cell: r => clamp2(r.profile) },
  { key: 'level', title: 'Ур.', width: 'w-[6%]' },
  { key: 'role', title: 'Кому', width: 'w-[12%]', hide: 'sm' },
  { key: 'confirm', title: 'ЕГЭ', width: 'w-[12%]', hide: 'sm' },
];

// ---------------------------------------------------------------- шапка
async function loadStats() {
  const data = await api('/api/stats');
  state.stats = data;
  const t = data.totals;
  $('#counters').innerHTML = [
    ['Вузов', t.universities, 'в базе'],
    ['Направлений', t.programs, 'и групп программ'],
    ['Олимпиад', t.olympiads, `${fmt(t.profiles)} профилей`],
    ['Строк таблиц', t.rows, `${fmt(t.bvi)} БВИ · ${fmt(t.sto)} по 100`],
  ].map(([label, value, hint]) => `
    <div class="stat">
      <div class="stat-label">${label}</div>
      <div class="stat-value">${fmt(value)}</div>
      <div class="stat-hint">${esc(hint)}</div>
    </div>`).join('');

  renderAbout(data);
}

function renderAbout(data) {
  const rows = data.universities.map(u => `
    <tr>
      <td>${esc(u.name)}</td>
      <td class="meta-text">${esc(place(u))}</td>
      <td class="num">${fmt(u.programs)}</td>
      <td class="num text-bvi font-medium">${fmt(u.bvi)}</td>
      <td class="num text-sto font-medium">${fmt(u.sto)}</td>
      <td class="num meta-text">${fmt(u.benefits)}</td>
    </tr>`).join('');
  const sheets = data.sheets.map(s => `
    <tr>
      <td>${esc(s.sheet)}</td>
      <td class="num">${fmt(s.rows_read)}</td>
      <td class="num">${fmt(s.benefits)}</td>
      <td class="meta-text pl-2">${esc(s.comment)}</td>
    </tr>`).join('');

  $('#about-body').innerHTML = `
    <p class="meta-text leading-relaxed">
      Источник — таблица <b>${esc(data.source_file)}</b> (17 листов приёмных кампаний 2026).
      База собрана ${esc(data.built_at)}: ${fmt(data.totals.programs)} направлений,
      ${fmt(data.totals.rows)} строк таблиц и ${fmt(data.totals.notes)} текстовых правил,
      ${fmt(data.totals.olympiads)} олимпиад с ${fmt(data.totals.profiles)} профилями,
      ${fmt(data.totals.links)} связей.
    </p>
    <div>
      <h3 class="block-title mb-1">Вузы</h3>
      <div class="scroll-y">
        <table class="about-table">
          <thead><tr>
            <th>Вуз</th><th>Город</th><th class="num">Напр.</th><th class="num">БВИ</th>
            <th class="num">100</th><th class="num">Всего</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>
    <div>
      <h3 class="block-title mb-1">Что разобрал парсер</h3>
      <div class="scroll-y">
        <table class="about-table">
          <thead><tr>
            <th>Лист</th><th class="num">Строк</th><th class="num">Льгот</th><th class="pl-2">Комментарий</th></tr></thead>
          <tbody>${sheets}</tbody>
        </table>
      </div>
    </div>
    <p class="text-xs meta-text">
      Данные справочные: перед подачей документов сверяйтесь с правилами приёма вуза
      (кнопка «Документ вуза» есть в карточке направления).
    </p>`;
}

// ---------------------------------------------------------------- фильтры
function renderFilters() {
  $('#type-filter').innerHTML = TYPES.map(t =>
    `<button class="chip ${state.benefitType === t ? 'chip-on' : ''}" data-type="${esc(t)}">${esc(t)}</button>`).join('');

  $$('#type-filter .chip').forEach(btn => btn.onclick = () => {
    state.benefitType = btn.dataset.type;
    renderFilters();
    if (state.tab === 'olymp' && state.query) runOlympiadSearch();
    else if (state.programData) renderProgram(state.programData);
  });
}

// ---------------------------------------------------------------- комбобокс
function setupCombo(rootSel, { onSearch, onPick, placeholder }) {
  const root = $(rootSel);
  const btn = $('.combo-btn', root);
  const panel = $('.combo-panel', root);
  const search = $('.combo-search', root);
  const list = $('.combo-list', root);
  let items = [];

  const close = () => { panel.classList.add('hidden'); btn.setAttribute('aria-expanded', 'false'); };
  const open = async () => {
    panel.classList.remove('hidden');
    btn.setAttribute('aria-expanded', 'true');
    search.value = '';
    search.focus();
    await refresh('');
  };

  async function refresh(q) {
    list.innerHTML = '<div class="suggest-empty">Загрузка…</div>';
    items = await onSearch(q);
    if (!items.length) {
      list.innerHTML = '<div class="suggest-empty">Ничего не найдено</div>';
      return;
    }
    list.innerHTML = items.map((item, i) =>
      `<button class="combo-item" data-i="${i}">${item.html}</button>`).join('');
    $$('.combo-item', list).forEach(el => el.onclick = () => {
      const item = items[+el.dataset.i];
      setComboValue(btn, item.label);
      close();
      onPick(item.value);
    });
  }

  btn.onclick = () => panel.classList.contains('hidden') ? open() : close();
  search.oninput = debounce(() => refresh(search.value.trim()), 180);
  document.addEventListener('click', e => { if (!root.contains(e.target)) close(); });

  return {
    reset(text) {
      const value = btn.querySelector('.combo-value');
      value.textContent = text || placeholder;
      value.classList.add('is-placeholder');
      close();
    },
    set(text) { setComboValue(btn, text); },
    setDisabled(flag) {
      btn.disabled = flag;
      if (flag) btn.title = 'Сначала выберите вуз'; else btn.removeAttribute('title');
    },
  };
}

function setComboValue(btn, text) {
  const value = btn.querySelector('.combo-value');
  value.textContent = text;
  value.classList.remove('is-placeholder');
}

// ---------------------------------------------------------------- таб 1
let comboUniversity, comboProgram;

async function loadUniversities() {
  const data = await api('/api/universities');
  state.universities = data.items;
}

function resetUniversityTab() {
  state.university = null; state.program = null; state.programData = null;
  comboUniversity.reset('Выберите вуз');
  comboProgram.reset('Выберите направление');
  comboProgram.setDisabled(true);
  $('#program-result').innerHTML = illuState('uni', UNI_START);
}

function resetOlympiadTab() {
  Object.assign(state, { query: '', olympiad: null, profileId: null,
                         olympiadData: null, pickedUniversity: null, universityData: null });
  $('#olymp-input').value = '';
  hideSuggest();
  $('#olymp-result').innerHTML = illuState('olymp', OLYMP_START);
}

function universityItems(q) {
  const needle = (q || '').toLowerCase();
  return state.universities
    .filter(u => !needle || u.name.toLowerCase().includes(needle))
    .map(u => ({
      value: u,
      label: u.name,
      html: `<span>${esc(u.name)}</span>
             <span class="meta">${esc(place(u))} · ${fmt(u.programs)} ${plural(u.programs, 'направление', 'направления', 'направлений')}
             · <span class="text-bvi">${fmt(u.bvi)} БВИ</span> · <span class="text-sto">${fmt(u.sto)} по 100</span></span>`,
    }));
}

async function programItems(q) {
  if (!state.university) return [];
  const query = q ? `&q=${encodeURIComponent(q)}` : '';
  const data = await api(`/api/programs?university_id=${state.university.id}${query}`);
  return data.items.map(p => ({
    value: p,
    label: p.faculty_or_direction,
    html: `<span>${esc(p.faculty_or_direction)}</span>
           <span class="meta">${p.code ? esc(p.code) + ' · ' : ''}<span class="text-bvi">${fmt(p.bvi)} БВИ</span>
           · <span class="text-sto">${fmt(p.sto)} по 100</span></span>`,
  }));
}

function pickUniversity(university) {
  state.university = university;
  state.program = null;
  state.programData = null;
  comboProgram.setDisabled(false);
  comboProgram.reset('Выберите направление');
  $('#program-result').innerHTML = illuState('uni',
    `Теперь выбери направление: в ${university.name} их ${fmt(university.programs)} в базе`);
}

async function pickProgram(program) {
  state.program = program;
  $('#program-result').innerHTML = SKELETON;
  const data = await api(`/api/search/by-program?program_id=${program.id}`);
  state.programData = data;
  state.tables = {};
  renderProgram(data);
}

function programRows(group) {
  return group.rows.map(b => ({
    olympiad: b.olympiads[0]?.short_name || '—',
    olympiad_id: b.olympiads[0]?.id || '',
    profile: dash(b.olympiad_profile || b.olympiad_subject),
    level: dash(b.level),
    role: dash(b.winner_role),
    grade: dash(b.grade),
    confirm: dash(b.confirm_subject),
    min_ege: dash(b.min_ege),
    derived: b.derived,
  }));
}

/* Источник — главный способ перепроверить автоматически разобранную таблицу,
   поэтому показываем его кнопкой с названием документа, а не мелкой ссылкой. */
function sourceButton({ url, title, types = [], kind = 'file' }) {
  const isPdf = /\.pdf($|[?#])/i.test(url);
  const label = kind === 'page' ? 'Документы приёмной комиссии'
    : types.length === 1 ? `Документ вуза: ${types[0]}`
    : 'Открыть документ вуза';
  return `
    <a class="source-btn" href="${esc(url)}" target="_blank" rel="noopener">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
           stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>
      </svg>
      <span class="source-btn-text">
        <b>${esc(label)}${isPdf ? ' (PDF)' : ''}</b>
        ${title ? `<span>${esc(title)}</span>` : ''}
      </span>
    </a>`;
}

/* Источник — главный способ перепроверить автоматически разобранную таблицу.
   Первой идёт страница раздела вуза: её адрес живёт годами, а файлы на ней
   обновляются каждый сезон. Дальше — конкретные документы с этой страницы. */
function sourceBlock(sources) {
  const list = (Array.isArray(sources) ? sources : [sources])
    .filter(s => s && (s.url || '').trim());
  if (!list.length) return '';
  const page = list.find(s => s.kind === 'page');
  // у части вузов файлы называются одинаково (перечни по кампусам и годам) —
  // в карточке от них нет пользы, полный список всегда есть на странице раздела
  const byTitle = new Map();
  list.filter(s => s !== page)
      .forEach(s => byTitle.has(s.title) || byTitle.set(s.title, s));
  const files = [...byTitle.values()].slice(0, 3);
  return `
    <div class="mt-3 flex flex-wrap gap-2">${[page, ...files].filter(Boolean).map(sourceButton).join('')}</div>
    <p class="mt-2 text-[12px] leading-snug meta-text">
      Таблица собрана автоматически из документов вуза — перед подачей сверьтесь с оригиналом.
      ${page ? 'Актуальные файлы всегда лежат на странице приёмной комиссии.' : ''}
    </p>`;
}

function renderProgram(data) {
  const { program, university, groups, notes, olympiads } = data;
  const visible = groups.filter(g =>
    state.benefitType === 'Все' || g.type === state.benefitType || g.type === 'Особое право (БВИ/100)');

  const head = `
    <div class="card p-4">
      <div class="card-kicker">
        ${esc(university.name)}${place(university) ? ' · ' + esc(place(university)) : ''}
      </div>
      <h2 class="card-title mt-1">${esc(program.faculty_or_direction)}</h2>
      <div class="mt-3 flex flex-wrap gap-1.5">
        ${program.code ? `<span class="badge badge-soft">${esc(program.code)}</span>` : ''}
        ${groups.map(g => `<span class="badge ${TYPE_STYLE[g.type]?.badge || 'badge-soft'}">${esc(g.type)}: ${fmt(g.count)}</span>`).join('')}
      </div>
      ${university.note ? `<p class="mt-2 text-[12.5px] leading-snug meta-text">${esc(university.note)}</p>` : ''}
      ${sourceBlock(data.sources && data.sources.length ? data.sources : [program])}
    </div>`;

  const sections = visible.map((group, gi) => {
    const style = TYPE_STYLE[group.type] || { section: 'card', badge: 'badge-soft', title: group.type };
    const rows = programRows(group);
    return `
      <div class="${style.section} p-3">
        <div class="flex items-center gap-2 mb-3 px-1 pt-0.5">
          <h3 class="text-[15px]">${esc(style.title)}</h3>
          <span class="badge ${style.badge} ml-auto">${fmt(group.count)}</span>
        </div>
        ${renderTable(`program-${program.id}-${gi}`, PROGRAM_COLUMNS, rows,
                      { placeholder: 'Фильтр: олимпиада, профиль, предмет…' })}
      </div>`;
  }).join('');

  const notesBlock = notes.length ? `
    <details class="card p-4">
      <summary class="block-title flex items-center gap-2">
        Общие правила и примечания
        <span class="badge badge-soft">${fmt(notes.length)}</span>
        <svg class="chev ml-auto shrink-0" width="15" height="9" viewBox="0 0 15 9" fill="none"><path d="M1 1l6.5 6.5L14 1" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
      </summary>
      <ul class="notes-list">
        ${notes.map(n => `<li><span class="badge badge-soft">${esc(n.kind)}</span><div>${esc(n.text)}</div></li>`).join('')}
      </ul>
    </details>` : '';

  const olympiadBlock = olympiads.length ? `
    <div class="card p-4">
      <h3 class="block-title mb-1">Олимпиады этого направления</h3>
      <p class="text-[12.5px] meta-text mb-3">Нажмите, чтобы увидеть, куда ещё она даёт льготы</p>
      <div class="flex flex-wrap gap-1.5">
        ${olympiads.map(o => `
          <button class="chip chip-ghost" data-olympiad="${o.id}" data-name="${esc(o.short_name)}">
            ${esc(o.short_name)}
            ${o.types.includes('БВИ') ? '<span class="text-bvi font-medium">БВИ</span>' : ''}
            ${o.types.includes('100 баллов') ? '<span class="text-sto font-medium">100</span>' : ''}
          </button>`).join('')}
      </div>
    </div>` : '';

  const root = $('#program-result');
  root.innerHTML = head + (sections || emptyState('📄', 'Таблицы для этого направления нет',
    'В источнике правило сформулировано общим текстом — смотрите блок «Общие правила и примечания».')) +
    notesBlock + olympiadBlock;

  visible.forEach((group, gi) =>
    bindTable(root, `program-${program.id}-${gi}`, PROGRAM_COLUMNS, programRows(group),
              () => renderProgram(data)));

  $$('#program-result [data-olympiad]').forEach(btn => btn.onclick = () => {
    if (btn.dataset.olympiad) goToOlympiad(+btn.dataset.olympiad, btn.dataset.name);
  });
}

function goToOlympiad(id, name) {
  switchTab('olymp');
  $('#olymp-input').value = name;
  state.query = name;
  state.olympiad = { id, short_name: name };
  state.profileId = null;
  state.pickedUniversity = null;
  hideSuggest();
  runOlympiadSearch();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ---------------------------------------------------------------- таб 2
async function loadPopular() {
  const data = await api('/api/olympiads?limit=12');
  $('#popular-chips').innerHTML =
    '<span class="text-[12.5px] meta-text self-center mr-1">Популярные:</span>' +
    data.items.map(o => `<button class="chip" data-name="${esc(o.short_name)}" data-id="${o.id}">${esc(o.short_name)}</button>`).join('');
  $$('#popular-chips .chip').forEach(btn => btn.onclick = () =>
    goToOlympiad(+btn.dataset.id, btn.dataset.name));
}

function hideSuggest() { $('#olymp-suggest').classList.add('hidden'); }

const suggest = debounce(async () => {
  const q = $('#olymp-input').value.trim();
  if (q.length < 2) return hideSuggest();
  const data = await api(`/api/olympiads?q=${encodeURIComponent(q)}&limit=8`);
  const box = $('#olymp-suggest');
  if (!data.items.length) {
    box.innerHTML = `<div class="suggest-empty">Не нашли такую олимпиаду. Попробуйте часть названия — «проба», «воробьевы», «технологическая».</div>`;
    box.classList.remove('hidden');
    return;
  }
  box.innerHTML = data.items.map(o => `
    <div class="suggest-item" data-id="${o.id}" data-name="${esc(o.short_name)}">
      <div class="font-medium text-[15px]">${esc(o.short_name)}</div>
      <div class="text-[12.5px] meta-text truncate">${esc(o.canonical_name)}</div>
      <div class="mt-1.5 flex gap-1 flex-wrap">
        <span class="badge badge-bvi">${fmt(o.bvi_count)} БВИ</span>
        <span class="badge badge-sto">${fmt(o.sto_count)} по 100</span>
        <span class="badge badge-soft">${fmt(o.uni_count)} ${plural(o.uni_count, 'вуз', 'вуза', 'вузов')}</span>
      </div>
    </div>`).join('');
  box.classList.remove('hidden');
  $$('.suggest-item', box).forEach(el => el.onclick = () =>
    goToOlympiad(+el.dataset.id, el.dataset.name));
}, 200);

function searchParams(extra = {}) {
  const params = new URLSearchParams({ q: state.query });
  if (state.olympiad?.id) params.set('olympiad_id', state.olympiad.id);
  if (state.profileId) params.set('profile_id', state.profileId);
  if (state.benefitType !== 'Все') params.set('benefit_type', state.benefitType);
  Object.entries(extra).forEach(([k, v]) => params.set(k, v));
  return params.toString();
}

async function runOlympiadSearch() {
  const q = state.query || $('#olymp-input').value.trim();
  if (q.length < 2) return;
  state.query = q;
  state.pickedUniversity = null;
  state.universityData = null;
  $('#olymp-result').innerHTML = SKELETON;
  const data = await api('/api/search/by-olympiad?' + searchParams());
  state.olympiadData = data;
  state.tables = {};
  renderOlympiadResults();
}

async function pickResultUniversity(university) {
  state.pickedUniversity = university;
  $('#olymp-result').innerHTML = SKELETON;
  const data = await api('/api/search/by-olympiad?' + searchParams({ university_id: university.id }));
  state.universityData = data;
  state.tables = {};
  renderUniversityBenefits();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function olympiadHead(data, extra = '') {
  const o = data.matched_olympiads[0];
  const profile = data.profiles?.find(p => p.id === state.profileId);
  return `
    <div class="card p-4">
      <div class="card-kicker">Олимпиада</div>
      <h2 class="card-title mt-1">${esc(o.short_name)}</h2>
      <div class="text-[13px] leading-snug meta-text mt-1">${esc(o.canonical_name)}</div>
      ${profile ? `<div class="mt-2 text-[13.5px]"><span class="meta-text">Профиль:</span> <span class="font-medium">${esc(profile.name)}</span></div>` : ''}
      <div class="mt-3 flex flex-wrap gap-1.5">
        <span class="badge badge-bvi">${fmt(profile ? profile.bvi_count : o.bvi_count)} БВИ</span>
        <span class="badge badge-sto">${fmt(profile ? profile.sto_count : o.sto_count)} по 100</span>
        ${extra}
      </div>
    </div>`;
}

function profileChips(data) {
  if (!data.profiles?.length) return '';
  const total = data.profiles.reduce((s, p) => s + p.mentions, 0);
  return `
    <div class="card p-4">
      <div class="flex items-center gap-2 mb-3">
        <h3 class="block-title">Профиль олимпиады</h3>
        <span class="badge badge-soft">${fmt(data.profiles.length)}</span>
      </div>
      <div class="profile-chips scroll-y">
        <button class="chip ${state.profileId ? '' : 'chip-on'}" data-profile="">
          Все профили <span class="chip-count">${fmt(total)}</span>
        </button>
        ${data.profiles.map(p => `
          <button class="chip ${state.profileId === p.id ? 'chip-on' : ''}" data-profile="${p.id}"
                  title="${esc(p.name)}">
            ${esc(p.name.length > 44 ? p.name.slice(0, 43) + '…' : p.name)}
            <span class="chip-count">${fmt(p.mentions)}</span>
          </button>`).join('')}
      </div>
    </div>`;
}

function renderOlympiadResults() {
  const data = state.olympiadData;
  if (!data.matched_olympiads.length) {
    const fallback = (data.fallback || []).slice(0, 8);
    $('#olymp-result').innerHTML = `
      ${emptyState('🤷', 'Олимпиада не найдена',
        'Проверьте написание или выберите из подсказок: в базе олимпиады перечня РСОШ, ВсОШ и международные.')}
      ${fallback.length ? `<div class="card p-4"><h3 class="block-title mb-2">Похожее по тексту условий</h3>
        <ul class="space-y-1.5 text-[13.5px]">${fallback.map(f =>
          `<li><b>${esc(f.university)}</b> · ${esc(f.faculty_or_direction)} — ${esc(f.benefit_type)}</li>`).join('')}</ul></div>` : ''}`;
    return;
  }

  const head = olympiadHead(data, `
    <span class="badge badge-soft">${fmt(data.total_universities)} ${plural(data.total_universities, 'вуз', 'вуза', 'вузов')}</span>
    <span class="badge badge-soft">${fmt(data.total_programs)} ${plural(data.total_programs, 'направление', 'направления', 'направлений')}</span>`);

  const list = data.results.map(group => {
    const u = group.university;
    return `
      <button class="uni-row" data-university="${u.id}">
        <div class="uni-row-main">
          <div class="uni-row-name">${esc(u.name)}</div>
          <div class="uni-row-meta">${esc(place(u))} · ${fmt(group.programs_total)} ${plural(group.programs_total, 'направление', 'направления', 'направлений')}</div>
          <div class="uni-row-badges">
            ${group.bvi ? `<span class="badge badge-bvi">${fmt(group.bvi)} БВИ</span>` : ''}
            ${group.sto ? `<span class="badge badge-sto">${fmt(group.sto)} по 100</span>` : ''}
            ${group.other ? `<span class="badge badge-alt" title="Особое право, фаст-трек, доп. баллы">${fmt(group.other)} др.</span>` : ''}
          </div>
        </div>
        ${ICON_CHEVRON_RIGHT}
      </button>`;
  }).join('');

  $('#olymp-result').innerHTML = head + profileChips(data) +
    (data.results.length
      ? `<div class="card uni-list overflow-hidden">
           <div class="list-caption">Выберите вуз, чтобы увидеть льготы по направлениям</div>
           ${list}
         </div>`
      : emptyState('🔍', 'Под фильтры ничего не попало', 'Снимите фильтр по профилю или типу льготы.'));

  // выбранный профиль может оказаться ниже видимой области списка — докручиваем к нему
  const box = $('#olymp-result .profile-chips');
  const active = box && $('.chip-on', box);
  if (active) box.scrollTop = active.offsetTop - box.offsetTop - 6;

  bindResultEvents();
}

const codesOf = s => (String(s || '').match(/\d{2}\.\d{2}\.\d{2}/g) || []).sort().join(',');

function universityRows(data) {
  const rows = [];
  data.results.forEach(group => group.programs.forEach(p => {
    // у части вузов название направления — это и есть перечень кодов, не дублируем
    const code = codesOf(p.program.code) && codesOf(p.program.code) !== codesOf(p.program.faculty_or_direction)
      ? p.program.code : '';
    p.benefits.forEach(b => {
    rows.push({
      program: p.program.faculty_or_direction,
      program_profile: (p.program.profile_name || '').slice(0, 70),
      program_id: p.program.id,
      code: dash(code),
      type: b.benefit_type,
      profile: dash(b.matched?.profile || b.olympiad_profile),
      level: dash(b.matched?.level || b.level),
      role: dash(b.winner_role || b.matched?.role),
      confirm: [b.confirm_subject, b.min_ege && `≥${b.min_ege}`].filter(Boolean).join(' ') || '—',
      derived: b.derived,
    });
    });
  }));
  return rows;
}

/* Документ вуза для выдачи по олимпиаде: у направлений он общий, берём первый
   непустой, иначе — страницу приёмной комиссии из справочника вузов. */
function universitySource(data, university) {
  if (university.docs_url) {
    return [{ url: university.docs_url, title: university.docs_title, kind: 'page', types: [] }];
  }
  const seen = new Map();
  data.results.forEach(g => g.programs.forEach(p => {
    for (const b of p.benefits) {
      if (b.source_url && !seen.has(b.source_url)) {
        seen.set(b.source_url, { url: b.source_url, title: b.source_title, types: [b.benefit_type] });
      } else if (b.source_url) {
        const item = seen.get(b.source_url);
        if (!item.types.includes(b.benefit_type)) item.types.push(b.benefit_type);
      }
    }
    const pr = p.program;
    if (!seen.size && pr.source_url) seen.set(pr.source_url, { url: pr.source_url, title: pr.source_title, types: [] });
  }));
  if (!seen.size && university.site_url) seen.set(university.site_url, { url: university.site_url, title: '', types: [] });
  return [...seen.values()].slice(0, 3);
}

function renderUniversityBenefits() {
  const data = state.universityData;
  const u = state.pickedUniversity;
  const rows = universityRows(data);
  const tableId = `uni-${u.id}-${state.profileId || 'all'}`;

  const head = olympiadHead(data, `<span class="badge badge-soft">${esc(u.name)}</span>`);
  const back = `
    <button class="back-link" data-back>${ICON_CHEVRON_LEFT} Все вузы (${fmt(state.olympiadData.total_universities)})</button>`;

  const uniCard = `
    <div class="card p-4">
      <div class="card-kicker">${esc(place(u))} · ${fmt(data.total_programs)} ${plural(data.total_programs, 'направление', 'направления', 'направлений')}</div>
      <h3 class="card-title mt-1">${esc(u.name)}</h3>
      ${u.note ? `<p class="mt-2 text-[12.5px] leading-snug meta-text">${esc(u.note)}</p>` : ''}
      ${sourceBlock(universitySource(data, u))}
      <div class="mt-3">${renderTable(tableId, UNIVERSITY_COLUMNS, rows, { placeholder: 'Фильтр: направление, профиль, код…' })}</div>
    </div>`;

  $('#olymp-result').innerHTML = head + back + uniCard;
  bindTable($('#olymp-result'), tableId, UNIVERSITY_COLUMNS, rows, renderUniversityBenefits);
  bindResultEvents();
}

function bindResultEvents() {
  $$('#olymp-result [data-profile]').forEach(btn => btn.onclick = () => {
    state.profileId = btn.dataset.profile ? +btn.dataset.profile : null;
    runOlympiadSearch();
  });
  $$('#olymp-result [data-university]').forEach(btn => btn.onclick = () => {
    const group = state.olympiadData.results.find(r => r.university.id === +btn.dataset.university);
    if (group) pickResultUniversity(group.university);
  });
  const back = $('#olymp-result [data-back]');
  if (back) back.onclick = () => {
    state.pickedUniversity = null;
    state.tables = {};
    renderOlympiadResults();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };
  $$('#olymp-result [data-program]').forEach(btn => btn.onclick = () => openProgram(+btn.dataset.program));
}

async function openProgram(programId) {
  switchTab('uni');
  const data = await api(`/api/search/by-program?program_id=${programId}`);
  state.programData = data;
  state.program = data.program;
  state.tables = {};
  comboUniversity.set(data.university.name);
  comboProgram.setDisabled(false);
  comboProgram.set(data.program.faculty_or_direction);
  renderProgram(data);
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ---------------------------------------------------------------- табы
function switchTab(tab) {
  state.tab = tab;
  $$('.tab-btn').forEach(b => b.classList.toggle('tab-active', b.dataset.tab === tab));
  $('#tab-uni').classList.toggle('hidden', tab !== 'uni');
  $('#tab-olymp').classList.toggle('hidden', tab !== 'olymp');
}

// ---------------------------------------------------------------- старт
async function init() {
  renderFilters();
  $$('.tab-btn').forEach(b => b.onclick = () => switchTab(b.dataset.tab));

  comboUniversity = setupCombo('#combo-university', {
    placeholder: 'Выберите вуз',
    onSearch: async q => universityItems(q),
    onPick: pickUniversity,
  });
  comboProgram = setupCombo('#combo-program', {
    placeholder: 'Выберите направление',
    onSearch: programItems,
    onPick: pickProgram,
  });

  $('#olymp-input').addEventListener('input', () => {
    state.olympiad = null; state.profileId = null; suggest();
  });
  $('#olymp-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') { state.query = e.target.value.trim(); hideSuggest(); runOlympiadSearch(); }
    if (e.key === 'Escape') hideSuggest();
  });
  document.addEventListener('click', e => {
    if (!e.target.closest('#olymp-input') && !e.target.closest('#olymp-suggest')) hideSuggest();
  });

  $('#about-btn').onclick = () => $('#about-modal').classList.remove('hidden');
  $$('#about-modal [data-close]').forEach(el => el.onclick = () => $('#about-modal').classList.add('hidden'));

  // крестик в шапке макета — сброс выбора на обеих вкладках
  $('#reset-btn').onclick = () => {
    resetUniversityTab();
    resetOlympiadTab();
    state.tables = {};
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  try {
    await Promise.all([loadStats(), loadUniversities(), loadPopular()]);
  } catch (err) {
    const message =
      `<div class="col-span-full card p-4 text-sm text-red-600">Не удалось загрузить данные: ${esc(err.message)}.
       Проверьте, что бэкенд запущен и база собрана (<code>python ingest_data.py</code>).</div>`;
    $('#counters').innerHTML = message;
    $('#program-result').innerHTML = message;
  }
}

init();

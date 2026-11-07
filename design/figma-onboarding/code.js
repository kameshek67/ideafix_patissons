// Плагин рисует онбординг мини-приложения «Олимп» (3 экрана, 430×932) рядом с доской
// «Идея фикс». Всё — обычные слои с auto layout: шрифт Onest, токены из styles.css,
// 3D-иллюстрации берутся из этого же файла по хэшу изображения.
// Запуск: Figma desktop → Plugins → Development → Import plugin from manifest… → manifest.json.

const C = {
  brand: "#BC00F5",
  brandInk: "#7B00AD",
  soft: "#FCF5FF",
  softLine: "#EBCBF7",
  hair: "#F0E4F5",
  muted: "#6B5570",
  ink: "#000000",
  board: "#E9E6EC",
  bvi: ["#F8EBFF", "#7300A0", "#EACBF8"],
  sto: ["#F0EFFF", "#3A2DB5", "#D6D2FA"],
  softBadge: ["#F6F1F8", "#6B5570", "#EDE3F1"],
};

// 3D-иллюстрации макета (illu-uni.png, illu-olymp.png) — уже лежат в файле
const IMAGES = {
  uni: "d78b5806b1b29ec3aada0b976635f8bcebff0703",
  olymp: "163e3d1cf92a25ccd8872cb880c460ea622bde14",
};

const BOARD_ID = "29:6552"; // фрейм «Идея фикс»
const SECTION_NAME = "03 · Онбординг · 430";
const W = 430;
const H = 932;

const SLIDES = [
  {
    line1: "Выбери вуз",
    line2: "узнай олимпиады",
    body: "Выбери вуз и направление — покажем, какие олимпиады дают БВИ или 100 баллов и какой нужен балл ЕГЭ.",
    art: "uni",
    primary: "Далее",
    label: "Онбординг · 1 из 3",
    note: "Сценарий «Вузы»: что даёт направление",
  },
  {
    line1: "Олимпиада",
    line2: "куда с ней поступить",
    body: "Введи название олимпиады — увидишь все вузы, где она даёт льготы, с профилями и уровнями.",
    art: "olymp",
    primary: "Далее",
    label: "Онбординг · 2 из 3",
    note: "Сценарий «Олимпиады»: куда с дипломом",
  },
  {
    line1: "Мои дипломы",
    line2: "все льготы сразу",
    body: "Добавь свои дипломы — учтём степень, класс и год олимпиады. Список сохранится в профиле MAX.",
    art: "diplomas",
    primary: "Добавить диплом",
    secondary: "Начать без дипломов",
    label: "Онбординг · 3 из 3",
    note: "Вкладка «Дипломы» и профиль MAX",
  },
];

const ARROW_SVG =
  '<svg width="19" height="15" viewBox="0 0 19 15" fill="none" xmlns="http://www.w3.org/2000/svg">' +
  '<path d="M1.28 7.44H17.19M11.03 13.6L17.19 7.44 11.03 1.28" stroke="black" stroke-width="2.565" stroke-linecap="round"/></svg>';

// ---------------------------------------------------------------- помощники

function rgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return { r: ((n >> 16) & 255) / 255, g: ((n >> 8) & 255) / 255, b: (n & 255) / 255 };
}

function solid(hex, opacity) {
  return [{ type: "SOLID", color: rgb(hex), opacity: opacity === undefined ? 1 : opacity }];
}

function shadow(alpha, y, blur, color) {
  const c = rgb(color || "#590078");
  return {
    type: "DROP_SHADOW",
    color: { r: c.r, g: c.g, b: c.b, a: alpha },
    offset: { x: 0, y: y },
    radius: blur,
    spread: 0,
    visible: true,
    blendMode: "NORMAL",
  };
}

/** Фрейм с auto layout. dir: "VERTICAL" | "HORIZONTAL". */
function box(name, dir, o) {
  o = o || {};
  const f = figma.createFrame();
  f.name = name;
  f.layoutMode = dir;
  f.primaryAxisSizingMode = "AUTO";
  f.counterAxisSizingMode = "AUTO";
  f.itemSpacing = o.gap || 0;
  const p = o.pad || [0, 0, 0, 0]; // сверху, справа, снизу, слева
  f.paddingTop = p[0];
  f.paddingRight = p[1];
  f.paddingBottom = p[2];
  f.paddingLeft = p[3];
  f.primaryAxisAlignItems = o.main || "MIN";
  f.counterAxisAlignItems = o.cross || "MIN";
  f.fills = o.fill || [];
  if (o.radius) f.cornerRadius = o.radius;
  if (o.stroke) {
    f.strokes = solid(o.stroke);
    f.strokeWeight = 1;
    f.strokeAlign = "INSIDE";
  }
  if (o.effects) f.effects = o.effects;
  f.clipsContent = !!o.clip;
  return f;
}

/** Добавить в auto layout и задать поведение размеров: "FILL" | "HUG" | "FIXED". */
function add(parent, child, w, h) {
  parent.appendChild(child);
  if (w) child.layoutSizingHorizontal = w;
  if (h) child.layoutSizingVertical = h;
  return child;
}

/** На всю ширину родителя и фиксированной высоты (кнопки, верхняя строка).
 *  Высоту задаём до растягивания: resize() после FILL вернул бы фиксированную ширину. */
function addFullWidth(parent, child, height) {
  child.resize(child.width, height);
  return add(parent, child, "FILL", "FIXED");
}

function text(chars, o) {
  const t = figma.createText();
  t.fontName = { family: "Onest", style: o.weight === 500 ? "Medium" : "Regular" };
  t.characters = chars;
  t.fontSize = o.size;
  if (o.lh) t.lineHeight = { value: o.lh, unit: "PIXELS" };
  if (o.ls) t.letterSpacing = { value: o.ls, unit: "PERCENT" };
  t.fills = solid(o.color || C.ink);
  if (o.align) t.textAlignHorizontal = o.align;
  t.name = o.name || chars.slice(0, 40);
  return t;
}

/** Текст на всю ширину родителя с переносом строк. */
function wrapText(parent, chars, o) {
  const t = add(parent, text(chars, o), "FILL");
  t.textAutoResize = "HEIGHT";
  return t;
}

function image(name, key, w, h) {
  const r = figma.createRectangle();
  r.name = name;
  r.resize(w, h);
  const hash = IMAGES[key];
  if (hash && figma.getImageByHash(hash)) {
    r.fills = [{ type: "IMAGE", imageHash: hash, scaleMode: "FIT" }];
  } else {
    // иллюстрации нет в файле — оставляем место, чтобы вставить её вручную
    r.fills = solid(C.soft);
    r.cornerRadius = 30;
    r.name = name + " — вставьте иллюстрацию";
  }
  return r;
}

function badge(label, tone) {
  const b = box("Badge · " + label, "HORIZONTAL", {
    pad: [1, 9, 1, 9],
    radius: 30,
    fill: solid(tone[0]),
    stroke: tone[2],
    cross: "CENTER",
  });
  add(b, text(label, { size: 11.5, lh: 20, weight: 500, color: tone[1] }));
  return b;
}

function button(label, kind) {
  const primary = kind === "primary";
  const b = box("Button · " + label, "HORIZONTAL", {
    radius: 30,
    main: "CENTER",
    cross: "CENTER",
    fill: solid(primary ? C.brand : C.soft),
    stroke: primary ? C.brand : C.softLine,
    effects: primary ? [shadow(0.22, 6, 16, C.brand)] : [],
  });
  add(b, text(label, { size: 16, lh: 20, weight: 500, color: primary ? "#FFFFFF" : C.brandInk }));
  return b;
}

function dots(active, total) {
  const row = box("Progress", "HORIZONTAL", { gap: 6, cross: "CENTER" });
  for (let i = 0; i < total; i++) {
    const d = figma.createRectangle();
    d.name = i === active ? "dot · active" : "dot";
    d.resize(i === active ? 24 : 8, 8);
    d.cornerRadius = 4;
    d.fills = solid(i === active ? C.brand : C.softLine);
    add(row, d);
  }
  return row;
}

/** Карточка диплома — как строка во вкладке «Дипломы». */
function diplomaCard(name, profile, meta, badges, width) {
  const card = box("Diploma card", "VERTICAL", {
    gap: 2,
    pad: [14, 16, 14, 16],
    radius: 15,
    fill: solid("#FFFFFF"),
    stroke: C.hair,
    effects: [shadow(0.12, 12, 28)],
  });
  card.counterAxisSizingMode = "FIXED";
  card.resize(width, card.height);
  // «Олимпиада · профиль»: профиль — обычным начертанием и вторичным цветом, как в приложении
  const title = text(name + " · " + profile, { size: 15, lh: 20, weight: 500 });
  title.setRangeFills(name.length, title.characters.length, solid(C.muted));
  title.setRangeFontName(name.length, title.characters.length, { family: "Onest", style: "Regular" });
  add(card, title, "FILL").textAutoResize = "HEIGHT";
  add(card, text(meta, { size: 12.5, lh: 18, color: C.muted }));
  const row = box("Badges", "HORIZONTAL", { gap: 4, pad: [6, 0, 0, 0] });
  badges.forEach(function (b) {
    add(row, badge(b[0], b[1]));
  });
  add(card, row);
  return card;
}

function art(slide) {
  if (slide.art === "uni") return image("illu-uni", "uni", 305, 318);
  if (slide.art === "olymp") return image("illu-olymp", "olymp", 240, 260);
  // «Мои дипломы»: две карточки дипломов и кубок — из компонентов приложения
  const f = figma.createFrame();
  f.name = "Diplomas collage";
  f.resize(372, 330);
  f.fills = [];
  f.clipsContent = false;
  const back = diplomaCard("ВсОШ", "английский язык", "Победитель · 2026", [
    ["50 БВИ", C.bvi],
    ["139 по 100", C.sto],
    ["13 вузов", C.softBadge],
  ], 300);
  f.appendChild(back);
  back.x = 58;
  back.y = 196;
  back.rotation = -4;
  back.opacity = 0.92;
  const front = diplomaCard("«Высшая проба»", "математика", "Победитель · 11 класс · 2025", [
    ["224 БВИ", C.bvi],
    ["35 по 100", C.sto],
    ["16 вузов", C.softBadge],
  ], 320);
  f.appendChild(front);
  front.x = 8;
  front.y = 96;
  front.rotation = 3;
  const cup = image("illu-olymp", "olymp", 128, 139);
  f.appendChild(cup);
  cup.x = 236;
  cup.y = 0;
  return f;
}

function screen(slide, index) {
  const s = box("Onboarding " + (index + 1) + " · " + slide.line1, "VERTICAL", {
    radius: 32,
    clip: true,
    effects: [shadow(0.1, 24, 48)],
  });
  s.primaryAxisSizingMode = "FIXED";
  s.counterAxisSizingMode = "FIXED";
  s.resize(W, H);
  // фон приложения: белый с фиолетовым низом (body::before в styles.css)
  s.fills = [
    { type: "SOLID", color: rgb("#FFFFFF") },
    {
      type: "GRADIENT_LINEAR",
      gradientTransform: [
        [0, 1, 0],
        [-1, 0, 1],
      ],
      gradientStops: [
        { position: 0, color: { r: 1, g: 1, b: 1, a: 0 } },
        { position: 0.64, color: { r: 1, g: 1, b: 1, a: 0 } },
        { position: 1, color: { r: 188 / 255, g: 0, b: 245 / 255, a: 0.5 } },
      ],
    },
  ];

  // текст и иллюстрация — на фоне приложения, кнопки — в белой шторке снизу:
  // фиолетовый низ фона уходит под иллюстрацию и не спорит с текстом и кнопками
  const content = add(s, box("Content", "VERTICAL", { pad: [8, 16, 0, 16] }), "FILL", "FILL");

  // верхняя строка: шаг и «Пропустить»
  const top = addFullWidth(content, box("Top bar", "HORIZONTAL", { main: "SPACE_BETWEEN", cross: "CENTER" }), 56);
  add(top, text(index + 1 + " из " + SLIDES.length, { size: 13, lh: 18, color: C.muted }));
  if (index < SLIDES.length - 1) {
    add(top, text("Пропустить", { size: 15, lh: 20, weight: 500, color: C.brandInk }));
  }

  // заголовок в стиле героя приложения: строка со стрелкой и акцентная строка
  const copy = add(content, box("Copy", "VERTICAL", { gap: 12, pad: [8, 0, 0, 0] }), "FILL");
  const title = add(copy, box("Title", "VERTICAL"), "FILL");
  const row = add(title, box("Line 1", "HORIZONTAL", { gap: 16, cross: "CENTER" }));
  add(row, text(slide.line1, { size: 32, lh: 40, weight: 500, ls: -1 }));
  const arrow = figma.createNodeFromSvg(ARROW_SVG);
  arrow.name = "Arrow";
  add(row, arrow);
  add(title, text(slide.line2, { size: 32, lh: 40, weight: 500, ls: -1, color: C.brand, name: "Line 2" }));
  wrapText(copy, slide.body, { size: 16, lh: 22, color: C.muted, name: "Body" });

  // иллюстрация занимает всё свободное место между текстом и шторкой
  const stage = add(content, box("Illustration", "VERTICAL", { main: "CENTER", cross: "CENTER" }), "FILL", "FILL");
  add(stage, art(slide));

  // шторка: прогресс и кнопки (радиус 30 сверху — «шторка» из дизайн-системы)
  const sheet = add(
    s,
    box("Bottom sheet", "VERTICAL", {
      gap: 20,
      pad: [20, 16, 34, 16],
      cross: "CENTER",
      fill: solid("#FFFFFF"),
      effects: [shadow(0.08, -8, 24)],
    }),
    "FILL",
  );
  sheet.topLeftRadius = 30;
  sheet.topRightRadius = 30;
  add(sheet, dots(index, SLIDES.length));
  const buttons = add(sheet, box("Buttons", "VERTICAL", { gap: 8 }), "FILL");
  addFullWidth(buttons, button(slide.primary, "primary"), 50);
  if (slide.secondary) addFullWidth(buttons, button(slide.secondary, "secondary"), 50);
  return s;
}

function column(slide, index) {
  const col = box("Column " + (index + 1), "VERTICAL", { gap: 12 });
  const head = add(col, box("Label", "VERTICAL", { gap: 2 }));
  add(head, text(slide.label, { size: 17, lh: 22, weight: 500 }));
  add(head, text(slide.note, { size: 13, lh: 18, color: C.muted }));
  add(col, screen(slide, index));
  return col;
}

function notes() {
  const card = box("Notes", "VERTICAL", {
    gap: 8,
    pad: [24, 24, 24, 24],
    radius: 15,
    fill: solid("#FFFFFF"),
    stroke: C.hair,
  });
  card.counterAxisSizingMode = "FIXED";
  card.resize(1386, card.height);
  add(card, text("Поведение", { size: 15, lh: 20, weight: 500 }));
  [
    "Показывается один раз — при первом запуске мини-приложения (флаг на устройстве).",
    "Между экранами — свайп или «Далее»; «Пропустить» сразу открывает приложение на вкладке «Вузы».",
    "Последний экран: «Добавить диплом» открывает вкладку «Дипломы» с формой, «Начать без дипломов» — вкладку «Вузы».",
    "В MAX кнопка «Назад» в шапке возвращает на предыдущий шаг; на первом шаге её нет.",
    "Иллюстрации — 3D из макета; на третьем экране — карточки дипломов из интерфейса вкладки «Дипломы».",
  ].forEach(function (line) {
    wrapText(card, "•  " + line, { size: 14, lh: 20, color: C.muted });
  });
  return card;
}

async function main() {
  await figma.loadFontAsync({ family: "Onest", style: "Regular" });
  await figma.loadFontAsync({ family: "Onest", style: "Medium" });

  const section = box(SECTION_NAME, "VERTICAL", {
    gap: 32,
    pad: [64, 64, 64, 64],
    fill: solid(C.board),
  });
  const heading = add(section, box("Heading", "VERTICAL", { gap: 8 }));
  add(heading, text(SECTION_NAME, { size: 32, lh: 40, weight: 500 }));
  add(
    heading,
    text("Первый запуск мини-приложения: три шага, на первых двух — «Пропустить»", {
      size: 16,
      lh: 24,
      color: C.muted,
    }),
  );
  const row = add(section, box("Screens", "HORIZONTAL", { gap: 48 }));
  SLIDES.forEach(function (slide, i) {
    add(row, column(slide, i));
  });
  add(section, notes());

  figma.currentPage.appendChild(section);
  const board = await figma.getNodeByIdAsync(BOARD_ID);
  if (board && "x" in board) {
    section.x = board.x + board.width + 200;
    section.y = board.y;
  } else {
    section.x = figma.viewport.center.x - section.width / 2;
    section.y = figma.viewport.center.y - section.height / 2;
  }
  figma.currentPage.selection = [section];
  figma.viewport.scrollAndZoomIntoView([section]);
  figma.closePlugin("Готово: онбординг из трёх экранов — «" + SECTION_NAME + "»");
}

main().catch(function (e) {
  figma.closePlugin("Не получилось: " + (e && e.message ? e.message : String(e)));
});

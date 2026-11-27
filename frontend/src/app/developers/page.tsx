import type { Metadata } from "next";
import { CodeBlock } from "@/components/CodeBlock";
import { IconChevronLeft } from "@/components/icons";

export const metadata: Metadata = { title: "Для разработчиков — Олимп" };

const BASE = "https://ideafix.patissons.tech/api";

const METHODS: { id: string; title: string; text: string; code: string }[] = [
  {
    id: "olympiads",
    title: "Олимпиады по названию",
    text: "GET /v1/olympiads — q (название или сокращение, до 200 символов), featured, limit (1–200, по умолчанию 20), with_profile.",
    code: `curl "${BASE}/v1/olympiads?q=ломоносов&limit=5"`,
  },
  {
    id: "by-olympiad",
    title: "Вузы и льготы по олимпиаде",
    text: "GET /v1/search/by-olympiad — q (от 2 символов) или olympiad_id, а также profile_id, university_id, region, benefit_type, limit (до 2000). С view=summary приходит список вузов со счётчиками без строк льгот.",
    code: `curl "${BASE}/v1/search/by-olympiad?q=ломоносов&view=summary"`,
  },
  {
    id: "by-program",
    title: "Олимпиады по направлению",
    text: "GET /v1/search/by-program — program_id обязателен.",
    code: `curl "${BASE}/v1/search/by-program?program_id=1"`,
  },
  {
    id: "match",
    title: "Куда годится диплом",
    text: "GET /v1/achievements/match — diploma повторяется по числу дипломов. Ключ собирается так: олимпиада.профиль.степень.класс.год, где степень w — победитель, p — призёр; ключи отдаёт /v1/achievements/olympiads/{id}. Дополнительно: benefit_type, university_id, баллы ЕГЭ ege=предмет:балл, rules.",
    code: `curl -G "${BASE}/v1/achievements/match" \\
  --data-urlencode "diploma=высшаяпроба.математика.w.11.2025" \\
  --data-urlencode "ege=math:90" --data-urlencode "ege=inf:82"`,
  },
  {
    id: "goals",
    title: "Олимпиады для цели",
    text: "GET /v1/goals/olympiads — program_id повторяется, от одного до трёх направлений.",
    code: `curl "${BASE}/v1/goals/olympiads?program_id=1&program_id=2"`,
  },
  {
    id: "quality",
    title: "Качество данных",
    text: "GET /v1/quality — оценка извлечения, охват вузов и свежесть данных; то же показывает страница «Качество данных».",
    code: `curl "${BASE}/v1/quality"`,
  },
];

const MCP_TOOLS: [string, string][] = [
  ["search_olympiads", "поиск олимпиад по названию или сокращению"],
  ["benefits_by_olympiad", "вузы и льготы по олимпиаде, можно уточнить профиль и тип льготы"],
  ["university_programs", "вузы и направления по названию, профилю или коду"],
  ["olympiads_for_program", "олимпиады и типы льгот для направления"],
  ["match_diplomas", "где дипломы дают БВИ или 100 баллов"],
];

const MCP_CONFIG = `{
  "mcpServers": {
    "olymp": {
      "command": "uv",
      "args": ["run", "--project", "/путь/к/репозиторию/backend", "olymp-mcp"],
      "env": { "OLYMP_API_URL": "${BASE}" }
    }
  }
}`;

const META_EXAMPLE = `{
  "built_at": "2026-11-26",
  "rows": 12345,
  "format_version": "1.0",
  "license": "CC BY 4.0",
  "source": "...",
  "notice": "..."
}`;

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section id={id} className="card mt-4 p-4 sm:p-5">
      <h2 className="text-[18px] leading-[24px] font-medium">{title}</h2>
      {children}
    </section>
  );
}

const P = "mt-2 text-[14px] leading-[20px]";
const NOTE = "mt-3 text-[12.5px] leading-[17px] meta-text";

/** Страница «Для разработчиков»: HTTP API, MCP-сервер и открытый датасет. Статическая, без запросов к API. */
export default function DevelopersPage() {
  return (
    <>
      <header className="app-header">
        <div className="mx-auto max-w-5xl h-14 px-2 flex items-center">
          <a href="/" className="icon-btn" aria-label="На главную" title="На главную">
            <IconChevronLeft />
          </a>
          <div className="flex-1 text-center text-[17px] font-medium">Для разработчиков</div>
          <span className="w-10 shrink-0" aria-hidden="true" />
        </div>
      </header>
      <main className="mx-auto max-w-2xl px-4 pb-16">
        <h1 className="mt-4 text-[26px] leading-[32px] font-medium">Данные Олимпа — открытые</h1>
        <p className="mt-2 text-[14px] leading-[20px] meta-text">
          Те же данные, что на сайте, доступны программам: HTTP API, MCP-сервер и файл с датасетом. Всё справочное: условия
          приёма перед подачей документов сверяй с официальными документами вуза.
        </p>

        <Section id="dev-api" title="HTTP API">
          <p className={P}>
            Базовый адрес — <code>{BASE}</code>. Ответы в JSON, ключ не нужен. Полное описание всех методов и схем — в{" "}
            <a id="dev-swagger" className="underline" href="/docs">
              Swagger
            </a>{" "}
            (<code>/docs</code>), файл схемы — <code>/openapi.json</code>.
          </p>
          <p className={P}>
            Лимит — 600 запросов в минуту с одного адреса. Если превысить, API отвечает 429 с заголовком{" "}
            <code>Retry-After</code>: подожди столько секунд.
          </p>
          <h3 className="mt-4 text-[15px] leading-[20px] font-medium">Главные методы</h3>
          {METHODS.map((m) => (
            <div key={m.id} id={`dev-method-${m.id}`} className="mt-4">
              <div className="text-[14.5px] leading-[20px] font-medium">{m.title}</div>
              <p className="mt-1 text-[13.5px] leading-[19px] meta-text">{m.text}</p>
              <CodeBlock code={m.code} label="curl" />
            </div>
          ))}
        </Section>

        <Section id="dev-mcp" title="MCP-сервер">
          <p className={P}>
            Сервер <code>olymp-mcp</code> отдаёт данные Олимпа любому клиенту MCP. Он ничего не хранит и ходит только в
            публичное API выше. Работает по stdio.
          </p>
          <ul className="mt-3 space-y-1.5 text-[14px] leading-[20px]">
            {MCP_TOOLS.map(([name, text]) => (
              <li key={name}>
                <code>{name}</code> — {text}
              </li>
            ))}
          </ul>
          <p className={P}>
            Запуск из репозитория: <code>uv run --project backend olymp-mcp</code>. Адрес API берётся из переменной{" "}
            <code>OLYMP_API_URL</code>; без неё сервер ходит на {BASE}. Свой стенд — например{" "}
            <code>http://127.0.0.1:8000</code>.
          </p>
          <CodeBlock code={MCP_CONFIG} label="Конфиг клиента MCP (JSON)" />
          <p className={NOTE}>Путь к репозиторию замени на свой; точное имя файла конфига смотри в документации клиента.</p>
        </Section>

        <Section id="dev-dataset" title="Открытый датасет">
          <p className={P}>
            Одна строка — одна видимая в выдаче льгота: вуз, направление, тип льготы, олимпиада, профиль, уровень, класс,
            баллы ЕГЭ, источник и год кампании. Файл — JSON Lines, сжатый gzip. Лицензия — CC BY 4.0: пользуйся и
            пересобирай, указывая источник.
          </p>
          <CodeBlock
            code={`just dataset
# или
cd backend && uv run olymp-export-dataset --output olymp-benefits.jsonl.gz --campaign 2026`}
            label="Собрать из базы"
          />
          <p className={P}>
            Результат — <code>data/release/olymp-benefits.jsonl.gz</code>, рядом лежит <code>meta.json</code> с датой
            сборки, числом строк, версией формата и лицензией.
          </p>
          <CodeBlock code={META_EXAMPLE} label="meta.json" />
          <CodeBlock code="zcat olymp-benefits.jsonl.gz | head -n 1" label="Посмотреть первую строку" />
        </Section>

        <Section id="dev-feedback" title="Нашёл ошибку">
          <p className={P}>
            Если льгота не совпадает с документом вуза — нажми «Нашли ошибку в данных? Напишите» под источниками в карточке направления: мы
            проверим строку по документу и поправим данные. Про ошибки самого API, MCP-сервера или датасета пиши в{" "}
            <a className="underline" href="https://github.com/kameshek67/ideafix_patissons/issues">
              issues на GitHub
            </a>
            . Личные данные в сообщения не добавляй.
          </p>
          <p className={NOTE}>
            Насколько данным можно верить — на странице{" "}
            <a className="underline" href="/quality">
              «Качество данных»
            </a>
            .
          </p>
        </Section>
      </main>
    </>
  );
}

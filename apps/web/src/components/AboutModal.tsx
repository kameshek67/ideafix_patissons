"use client";

import { IconCloseModal } from "./icons";

interface Props {
  open: boolean;
  onClose: () => void;
  /** Приёмная кампания: годы, за которые засчитываются дипломы (из `/v1/max/config`). */
  campaign: { campaign_year: number; valid_years: number[] };
}

const SCENARIOS: [string, string][] = [
  ["Вузы", "Выбери направление — покажем олимпиады, которые дают льготу"],
  ["Олимпиады", "Введи название — покажем вузы, где диплом сработает"],
  ["Дипломы", "Добавь свои дипломы — соберём все льготы сразу"],
];

/** Строки «термин — пояснение» с тонкими разделителями. */
function Rows({ items }: { items: [string, string][] }) {
  return (
    <dl className="divide-y divide-[color:var(--hair)]">
      {items.map(([term, text]) => (
        <div key={term} className="grid grid-cols-[96px_1fr] gap-3 py-2.5">
          <dt className="font-medium">{term}</dt>
          <dd className="meta-text">{text}</dd>
        </div>
      ))}
    </dl>
  );
}

/** «О приложении»: шторка снизу на телефоне, окно по центру на десктопе. */
export function AboutModal({ open, onClose, campaign }: Props) {
  const years = campaign.valid_years;
  const period = years.length ? `${years[0]}–${years[years.length - 1]}` : "последних четырёх";
  const conditions: [string, string][] = [
    ["Профиль", "Должен подходить к направлению, например «математика»"],
    ["Уровень", "I, II или III в перечне олимпиад — от него зависит льгота"],
    ["Степень", "Победитель или призёр: БВИ часто дают только победителям"],
    ["Срок", `Засчитываются олимпиады ${period} годов`],
    ["ЕГЭ", "Льготу подтверждают баллами по предмету, обычно от 75"],
  ];

  return (
    <div
      id="about-modal"
      className={open ? "fixed inset-0 z-40" : "fixed inset-0 z-40 hidden"}
      role="dialog"
      aria-modal="true"
      aria-labelledby="about-title"
    >
      <div className="absolute inset-0 bg-[#2A0038]/40 backdrop-blur-[2px]" onClick={onClose} />
      <div className="about-sheet absolute inset-x-0 bottom-0 sm:inset-0 sm:m-auto sm:h-fit sm:max-w-[520px] bg-white rounded-t-[30px] sm:rounded-[30px] p-5 pb-[calc(20px+env(safe-area-inset-bottom))] sm:p-6 max-h-[85vh] sm:max-h-[90vh] overflow-y-auto">
        <div className="sheet-handle sm:hidden" />
        <div className="flex items-center justify-between">
          <h2 id="about-title" className="text-[20px] font-medium">
            О приложении
          </h2>
          <button className="icon-btn -mr-2" onClick={onClose} aria-label="Закрыть">
            <IconCloseModal />
          </button>
        </div>

        <div id="about-body" className="text-[14.5px] leading-[20px]">
          <p className="mt-2 meta-text">
            «Олимп» показывает, где олимпиадный диплом даёт льготу при поступлении.
          </p>

          <div className="mt-6 grid grid-cols-2 gap-2">
            <div className="rounded-[15px] bg-bvi-bg p-3.5">
              <div className="text-[17px] font-medium text-bvi">БВИ</div>
              <p className="mt-1 text-[13px] leading-[18px] meta-text">Без вступительных экзаменов</p>
            </div>
            <div className="rounded-[15px] bg-sto-bg p-3.5">
              <div className="text-[17px] font-medium text-sto">100 баллов</div>
              <p className="mt-1 text-[13px] leading-[18px] meta-text">Вместо ЕГЭ по профилю</p>
            </div>
          </div>

          <h3 className="mt-6 card-kicker">Как пользоваться</h3>
          <Rows items={SCENARIOS} />

          <h3 className="mt-5 card-kicker">От чего зависит льгота</h3>
          <Rows items={conditions} />

          <p className="mt-5 text-[12.5px] leading-[17px] meta-text">
            Условия у вузов разные — перед подачей сверься с документом вуза в карточке направления.
          </p>
          <p className="mt-2 text-[12.5px] leading-[17px] meta-text">
            Числа у «БВИ» и «100 баллов» — строки таблиц льгот (олимпиада × профиль × направление), а не количество вузов
            или людей.
          </p>
        </div>
      </div>
    </div>
  );
}

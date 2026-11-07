"use client";

import type { ReactNode } from "react";
import { IconCloseModal } from "./icons";
import { useMax } from "./MaxProvider";

interface Props {
  open: boolean;
  onClose: () => void;
  /** Приёмная кампания: годы, за которые засчитываются дипломы (из `/v1/max/config`). */
  campaign: { campaign_year: number; valid_years: number[] };
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h3 className="block-title mb-2">{title}</h3>
      {children}
    </section>
  );
}

function Benefit({ tone, title, children }: { tone: "bvi" | "sto" | "alt"; title: string; children: ReactNode }) {
  return (
    <div className={`section-${tone} px-3.5 py-3`}>
      <h3 className="text-[14px]">{title}</h3>
      <p className="mt-1 text-[13.5px] leading-[1.45]">{children}</p>
    </div>
  );
}

/** «О приложении»: шторка снизу на телефоне, окно по центру на десктопе. */
export function AboutModal({ open, onClose, campaign }: Props) {
  const inMax = !!useMax();
  const years = campaign.valid_years;
  const period = years.length ? `${years[0]}–${years[years.length - 1]}` : "";

  return (
    <div
      id="about-modal"
      className={open ? "fixed inset-0 z-40" : "fixed inset-0 z-40 hidden"}
      role="dialog"
      aria-modal="true"
      aria-labelledby="about-title"
    >
      <div className="absolute inset-0 bg-[#2A0038]/40 backdrop-blur-[2px]" onClick={onClose} />
      <div className="absolute inset-x-0 bottom-0 sm:inset-0 sm:m-auto sm:h-fit sm:max-w-2xl bg-white rounded-t-[30px] sm:rounded-[30px] p-5 max-h-[85vh] overflow-y-auto">
        <div className="sheet-handle sm:hidden" />
        <div className="flex items-center justify-between mb-3">
          <h2 id="about-title" className="text-[20px] font-medium">
            О приложении
          </h2>
          <button className="icon-btn -mr-2" onClick={onClose} aria-label="Закрыть">
            <IconCloseModal />
          </button>
        </div>

        <div id="about-body" className="space-y-5 text-sm">
          <p className="leading-relaxed">
            «Олимп» показывает, где олимпиадный диплом даёт льготу при поступлении: <b>БВИ</b> или{" "}
            <b>100 баллов</b> за экзамен. Работает на сайте и как мини-приложение в MAX.
          </p>

          <Section title="Что можно сделать">
            <ul className="notes-list !mt-0">
              <li>
                <b>Вузы → олимпиады.</b> Выбери вуз и направление — покажем олимпиады, которые дают льготу,
                и балл ЕГЭ, которым её нужно подтвердить.
              </li>
              <li>
                <b>Олимпиада → вузы.</b> Введи название олимпиады — увидишь все вузы, где она даёт льготу, с
                профилями и уровнями.
              </li>
              <li>
                <b>Мои дипломы → все льготы.</b> Добавь свои дипломы — соберём льготы во всех вузах с учётом
                их условий. Список хранится {inMax ? "в профиле MAX" : "на этом устройстве"}.
              </li>
            </ul>
          </Section>

          <Section title="Какие бывают льготы">
            <div className="grid gap-2">
              <Benefit tone="bvi" title="БВИ — без вступительных испытаний">
                Диплом заменяет все вступительные экзамены на направление, а такие абитуриенты зачисляются в
                первую очередь.
              </Benefit>
              <Benefit tone="sto" title="100 баллов за ЕГЭ или ДВИ">
                Диплом засчитывается как 100 баллов по профильному предмету. Остальные экзамены считаются по
                твоим результатам.
              </Benefit>
              <Benefit tone="alt" title="Другие льготы">
                Некоторые вузы дают своё: особое право на выбор БВИ или 100 баллов, дополнительные баллы за
                индивидуальные достижения, ускоренное зачисление.
              </Benefit>
            </div>
          </Section>

          <Section title="От чего зависит льгота">
            <ul className="notes-list !mt-0">
              <li>
                <b>Профиль.</b> Льготу дают за конкретный профиль олимпиады — например, «математика», — и он
                должен подходить к направлению.
              </li>
              <li>
                <b>Уровень олимпиады.</b> В перечне олимпиад школьников у каждого профиля свой уровень: I, II
                или III (I — самый высокий). От уровня зависит, какую льготу даст вуз.
              </li>
              <li>
                <b>Степень диплома.</b> Победитель или призёр: многие вузы дают БВИ только победителям.
              </li>
              <li>
                <b>Класс.</b> Часть вузов учитывает, в каком классе получен диплом.
              </li>
              <li>
                <b>Срок.</b> Дипломы действуют четыре года
                {period ? `: в ${campaign.campaign_year} году засчитывают олимпиады ${period}` : ""}, если вуз не
                указал иное.
              </li>
              <li>
                <b>Подтверждение ЕГЭ.</b> Обычно льготу нужно подтвердить: сдать ЕГЭ по предмету олимпиады не
                ниже порога, чаще всего от 75 баллов. Порог указан в таблице направления.
              </li>
              <li>
                <b>ВсОШ.</b> Победители и призёры заключительного этапа Всероссийской олимпиады получают БВИ на
                профильные направления в любом вузе.
              </li>
            </ul>
          </Section>

          <p className="text-xs meta-text">
            Данные справочные: перед подачей документов сверься с правилами приёма вуза — кнопка «Документ вуза»
            есть в карточке направления.
          </p>
        </div>
      </div>
    </div>
  );
}

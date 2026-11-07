"use client";

import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import { haptic } from "@/lib/max";
import { markOnboardingDone } from "@/lib/onboarding";
import { IconHeroArrow } from "./icons";
import { useMax, useMaxBackButton } from "./MaxProvider";

/** Куда вести после онбординга. */
export type OnboardingExit = "uni" | "add-diploma";

interface Slide {
  line1: string;
  line2: string;
  body: (inMax: boolean) => string;
  art: ReactNode;
  /** естественный размер иллюстрации: на низких экранах она уменьшается целиком */
  size: [number, number];
}

/** Масштабирует содержимое так, чтобы оно поместилось в свободное место, не искажая его. */
function FitBox({ size: [width, height], children }: { size: [number, number]; children: ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const update = () => {
      const r = el.getBoundingClientRect();
      if (r.width && r.height) setScale(Math.min(1, r.width / width, r.height / height));
    };
    update();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [width, height]);
  return (
    <div ref={box} className="onboarding-art">
      <div style={{ width, height, flexShrink: 0, transform: `scale(${scale})` }}>{children}</div>
    </div>
  );
}

function DiplomaCard({
  name,
  profile,
  meta,
  badges,
  className,
}: {
  name: string;
  profile: string;
  meta: string;
  badges: [string, string][];
  className: string;
}) {
  return (
    <div className={`onboarding-diploma ${className}`}>
      <span className="diploma-name">
        {name}
        <span className="diploma-profile">{` · ${profile}`}</span>
      </span>
      <span className="diploma-meta">{meta}</span>
      <span className="uni-row-badges">
        {badges.map(([label, tone]) => (
          <span key={label} className={`badge ${tone}`}>
            {label}
          </span>
        ))}
      </span>
    </div>
  );
}

const SLIDES: Slide[] = [
  {
    line1: "Выбери вуз",
    line2: "узнай олимпиады",
    body: () =>
      "Выбери вуз и направление — покажем, какие олимпиады дают БВИ или 100 баллов и какой нужен балл ЕГЭ.",
    // eslint-disable-next-line @next/next/no-img-element
    art: <img src="/assets/illu-uni.png" alt="" width={305} height={318} />,
    size: [305, 318],
  },
  {
    line1: "Олимпиада",
    line2: "куда с ней поступить",
    body: () => "Введи название олимпиады — увидишь все вузы, где она даёт льготы, с профилями и уровнями.",
    // eslint-disable-next-line @next/next/no-img-element
    art: <img src="/assets/illu-olymp.png" alt="" width={240} height={260} />,
    size: [240, 260],
  },
  {
    line1: "Мои дипломы",
    line2: "все льготы сразу",
    body: (inMax) =>
      `Добавь свои дипломы — учтём степень, класс и год олимпиады. Список сохранится ${
        inMax ? "в профиле MAX" : "на этом устройстве"
      }.`,
    art: (
      <div className="onboarding-collage">
        <DiplomaCard
          className="is-back"
          name="ВсОШ"
          profile="английский язык"
          meta="Победитель · 2026"
          badges={[
            ["50 БВИ", "badge-bvi"],
            ["139 по 100", "badge-sto"],
            ["13 вузов", "badge-soft"],
          ]}
        />
        <DiplomaCard
          className="is-front"
          name="«Высшая проба»"
          profile="математика"
          meta="Победитель · 11 класс · 2025"
          badges={[
            ["224 БВИ", "badge-bvi"],
            ["35 по 100", "badge-sto"],
            ["16 вузов", "badge-soft"],
          ]}
        />
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className="onboarding-cup" src="/assets/illu-olymp.png" alt="" width={128} height={139} />
      </div>
    ),
    size: [372, 330],
  },
];

/** Знакомство с приложением при первом запуске: три шага, свайп или «Далее». */
export function Onboarding({ onFinish }: { onFinish: (exit: OnboardingExit) => void }) {
  const app = useMax();
  const [step, setStepState] = useState(0);
  // текущий шаг сразу, без ожидания перерисовки (для выравнивания ленты)
  const stepRef = useRef(0);
  const setStep = (value: number) => {
    stepRef.current = value;
    setStepState(value);
  };
  const track = useRef<HTMLDivElement>(null);
  const last = step === SLIDES.length - 1;

  function finish(exit: OnboardingExit) {
    markOnboardingDone();
    onFinish(exit);
  }

  // плавная прокрутка к экрану после «Далее»: пока она идёт, промежуточные положения ленты
  // шаг не меняют — иначе в начале пути шаг откатывался назад, и второе быстрое «Далее»
  // считалось от прежнего экрана
  const scrolling = useRef<{ target: number; timer?: ReturnType<typeof setTimeout> } | null>(null);
  useEffect(() => () => clearTimeout(scrolling.current?.timer), []);

  function go(next: number) {
    const target = Math.max(0, Math.min(SLIDES.length - 1, next));
    const el = track.current;
    if (el && typeof el.scrollTo === "function") {
      clearTimeout(scrolling.current?.timer);
      const left = target * el.clientWidth;
      // уже на месте — прокрутки и события scroll не будет
      scrolling.current = Math.abs(el.scrollLeft - left) < 1 ? null : { target };
      el.scrollTo({ left, behavior: "smooth" });
    }
    setStep(target);
    haptic(app, "select");
  }

  // свайп: шаг — по прокрутке ленты экранов
  function onScroll() {
    const el = track.current;
    if (!el || !el.clientWidth) return;
    const position = el.scrollLeft / el.clientWidth;
    const pending = scrolling.current;
    if (pending) {
      clearTimeout(pending.timer);
      if (Math.abs(position - pending.target) < 0.01) {
        scrolling.current = null; // доехали: дальше шаг снова следует за свайпом
      } else {
        // прокрутку перехватили пальцем — шаг сверяется с лентой, когда она остановится
        pending.timer = setTimeout(() => {
          scrolling.current = null;
          onScroll();
        }, 150);
      }
      return;
    }
    const current = Math.round(position);
    if (current !== stepRef.current) setStep(current);
  }

  // поворот телефона или смена ширины окна: лента остаётся ровно на текущем экране.
  // Только ширина: высота ленты меняется и на последнем шаге (в шторке две кнопки)
  useEffect(() => {
    const el = track.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    let width = el.clientWidth;
    const observer = new ResizeObserver(() => {
      if (el.clientWidth === width) return;
      width = el.clientWidth;
      el.scrollLeft = stepRef.current * width;
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // кнопка «Назад» в шапке MAX — на предыдущий шаг
  useMaxBackButton(step > 0 ? () => go(step - 1) : null);

  // страница под онбордингом не прокручивается; клавиатура — стрелки и Escape
  useEffect(() => {
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = overflow;
    };
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") finish("uni");
      if (e.key === "ArrowRight") go(step + 1);
      if (e.key === "ArrowLeft") go(step - 1);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  });

  return (
    <div id="onboarding" className="onboarding" role="dialog" aria-modal="true" aria-label="Знакомство с «Олимпом»">
      <div className="onboarding-card">
        <div className="onboarding-top">
          <span className="onboarding-step">{`${step + 1} из ${SLIDES.length}`}</span>
          {last ? null : (
            <button className="onboarding-skip" onClick={() => finish("uni")}>
              Пропустить
            </button>
          )}
        </div>

        <div className="onboarding-track" ref={track} onScroll={onScroll}>
          {SLIDES.map((slide, i) => (
            <section key={slide.line1} className="onboarding-slide" aria-hidden={i !== step}>
              <h2 className="onboarding-title">
                <span className="flex items-center gap-4">
                  {slide.line1}
                  <IconHeroArrow />
                </span>
                <span className="text-brand">{slide.line2}</span>
              </h2>
              <p className="onboarding-body">{slide.body(!!app)}</p>
              <FitBox size={slide.size}>{slide.art}</FitBox>
            </section>
          ))}
        </div>

        <div className="onboarding-sheet">
          <div className="onboarding-dots" aria-hidden="true">
            {SLIDES.map((slide, i) => (
              <span key={slide.line1} className={i === step ? "is-active" : ""} />
            ))}
          </div>
          <div className="onboarding-actions">
            {last ? (
              <>
                <button className="btn-primary w-full" onClick={() => finish("add-diploma")}>
                  Добавить диплом
                </button>
                <button className="btn-secondary w-full" onClick={() => finish("uni")}>
                  Начать без дипломов
                </button>
              </>
            ) : (
              <button className="btn-primary w-full" onClick={() => go(step + 1)}>
                Далее
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

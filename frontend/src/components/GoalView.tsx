"use client";

import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  friendlyError,
  getGoalOlympiads,
  getPrograms,
  type GoalOlympiad,
  type GoalOlympiads,
  type ProgramItem,
  type UniversityItem,
} from "@/lib/api";
import { fmt, place, plural } from "@/lib/format";
import {
  coverageLabels,
  egeLabel,
  goalTitle,
  MAX_GOAL_PROGRAMS,
  PRIZE_2027,
  whoLabel,
} from "@/lib/goals";
import { NOT_IN_LIST_BADGE, NOT_IN_LIST_HINT } from "@/lib/rsosh";
import { Combo, type ComboItem } from "./Combo";
import { IlluState, LoadError, Skeleton } from "./ui";

const START =
  "Выбери до трёх направлений, куда хочешь поступить, — покажем олимпиады, которые подходят сразу к нескольким";

interface Props {
  universities: UniversityItem[];
  /** тап по олимпиаде: экран олимпиады с выбранным профилем */
  goToOlympiad: (
    id: number,
    name: string,
    profileId: number | null,
    label: string,
  ) => void;
}

export function GoalList({
  data,
  onPick,
}: {
  data: GoalOlympiads;
  onPick: (item: GoalOlympiad) => void;
}) {
  const total = data.programs.length;
  if (!data.items.length) {
    return (
      <IlluState
        kind="uni"
        text="По этим направлениям в базе нет льгот по олимпиадам. Попробуй другие."
      />
    );
  }
  return (
    <div className="card p-4" id="goal-list">
      <ul className="diploma-list">
        {data.items.map((item) => {
          const ege = egeLabel(item);
          return (
            <li
              key={`${item.olympiad_id}-${item.profile_id ?? ""}`}
              className="diploma-row"
            >
              <button
                className="diploma-main"
                type="button"
                onClick={() => onPick(item)}
              >
                <span className="diploma-name">{goalTitle(item)}</span>
                <span className="diploma-meta">
                  {[
                    whoLabel(item),
                    item.level ? `уровень ${item.level}` : null,
                    ege,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
                <span className="uni-row-badges">
                  {coverageLabels(item, total).map((l) => (
                    <span
                      key={l.type}
                      className={
                        l.type === "БВИ" ? "badge badge-bvi" : "badge badge-sto"
                      }
                    >
                      {l.text}
                    </span>
                  ))}
                  {item.prize_hundred_2027 ? (
                    <span className="badge badge-soft" title={PRIZE_2027}>
                      {PRIZE_2027}
                    </span>
                  ) : null}
                  {item.in_list_2026_27 ? null : (
                    <span className="badge badge-alt" title={NOT_IN_LIST_HINT}>
                      {NOT_IN_LIST_BADGE}
                    </span>
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** «Подобрать олимпиады под цель»: до трёх направлений (можно из разных вузов) и рейтинг олимпиад. */
export function GoalView({ universities, goToOlympiad }: Props) {
  const queryClient = useQueryClient();
  const [university, setUniversity] = useState<UniversityItem | null>(null);
  const [programs, setPrograms] = useState<ProgramItem[]>([]);
  const ids = programs.map((p) => p.id);
  const full = programs.length >= MAX_GOAL_PROGRAMS;

  const goal = useQuery({
    queryKey: ["goal-olympiads", ids],
    queryFn: () => getGoalOlympiads(ids),
    enabled: ids.length > 0,
    staleTime: 60_000,
    // добавил или убрал направление: прежний рейтинг остаётся, пока считается новый
    placeholderData: keepPreviousData,
  });

  function universityItems(q: string): ComboItem<UniversityItem>[] {
    const needle = q.toLowerCase();
    return universities
      .filter((u) => !needle || u.name.toLowerCase().includes(needle))
      .map((u) => ({
        key: u.id,
        value: u,
        label: u.name,
        content: (
          <>
            <span>{u.name}</span>
            <span className="meta">{`${place(u)} · ${fmt(u.programs)} ${plural(u.programs, "направление", "направления", "направлений")}`}</span>
          </>
        ),
      }));
  }

  async function programItems(q: string): Promise<ComboItem<ProgramItem>[]> {
    if (!university) return [];
    const data = await queryClient.fetchQuery({
      queryKey: ["programs", university.id, q],
      queryFn: () => getPrograms(university.id, q),
      staleTime: 60_000,
    });
    return data.items
      .filter((p) => !ids.includes(p.id))
      .map((p) => ({
        key: p.id,
        value: p,
        label: p.faculty_or_direction,
        content: (
          <>
            <span>{p.faculty_or_direction}</span>
            <span className="meta">{p.code || p.profile_name}</span>
          </>
        ),
      }));
  }

  return (
    <div className="space-y-3" id="goal-view">
      <div className="grid sm:grid-cols-2 gap-2">
        <Combo<UniversityItem>
          id="goal-combo-university"
          ariaLabel="Вуз цели"
          placeholder="Выбери вуз"
          searchPlaceholder="Поиск вуза…"
          value={university?.name ?? null}
          disabled={full}
          disabledTitle="Выбрано три направления"
          onSearch={universityItems}
          onPick={(item) => setUniversity(item.value)}
        />
        <Combo<ProgramItem>
          id="goal-combo-program"
          ariaLabel="Направление цели"
          placeholder="Добавь направление"
          searchPlaceholder="Поиск направления или кода…"
          value={null}
          disabled={!university || full}
          disabledTitle={
            full ? "Выбрано три направления" : "Сначала выбери вуз"
          }
          onSearch={programItems}
          onPick={(item) => setPrograms((list) => [...list, item.value])}
        />
      </div>

      {programs.length ? (
        <ul
          className="flex flex-wrap gap-1.5"
          id="goal-programs"
          aria-label="Выбранные направления"
        >
          {programs.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                className="chip chip-on"
                title="Убрать из цели"
                aria-label={`Убрать: ${p.university_short}, ${p.faculty_or_direction}`}
                onClick={() =>
                  setPrograms((list) => list.filter((x) => x.id !== p.id))
                }
              >
                {`${p.university_short} · ${p.faculty_or_direction}`} ×
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      <div id="goal-result" className="busy-line space-y-3" data-busy={goal.isPlaceholderData || undefined} aria-busy={goal.isPlaceholderData || undefined}>
        {!ids.length ? (
          <IlluState kind="uni" text={START} />
        ) : goal.isPending ? (
          <Skeleton />
        ) : goal.error ? (
          <LoadError
            message={friendlyError(goal.error)}
            onRetry={() => void goal.refetch()}
          />
        ) : (
          <GoalList
            data={goal.data}
            onPick={(i) =>
              goToOlympiad(
                i.olympiad_id,
                i.short_name,
                i.profile_id ?? null,
                goalTitle(i),
              )
            }
          />
        )}
      </div>
    </div>
  );
}

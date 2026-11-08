/* Куда перейти внутри приложения. Пока здесь только то, что нужно карточкам помощника;
   стек «Назад» и разбор ссылок запуска — задача T-062. */

export type ScreenIntent =
  | { kind: "program"; id: number }
  | { kind: "olympiad"; id: number; name: string }
  | { kind: "university"; id: number };

export interface EntityRef {
  kind: "olympiad" | "program" | "university";
  id: number;
  label: string;
}

export function entityIntent(entity: EntityRef): ScreenIntent {
  if (entity.kind === "olympiad") return { kind: "olympiad", id: entity.id, name: entity.label };
  return { kind: entity.kind, id: entity.id };
}

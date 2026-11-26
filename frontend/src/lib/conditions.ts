/** Условия льготы одной строкой — для узких экранов, где колонки «Кому», «Класс» и «ЕГЭ» скрыты. */

export interface ConditionParts {
  role?: string;
  grade?: string;
  /** предмет ЕГЭ; может уже содержать порог («информатика ≥75») */
  confirm?: string;
  /** порог отдельно («75 и более») */
  min_ege?: string;
}

const present = (v?: string): v is string => !!v && v !== "—";

/** «75 и более» в таблицах вузов — то же, что «≥75». */
const threshold = (v: string) => `≥${v.replace(/\s*и\s+более\s*$/i, "").replace(/^≥\s*/, "")}`;

/** «победители и призёры · 11 класс · ЕГЭ математика ≥75»; пустая строка, если условий нет. */
export function conditionsLine(p: ConditionParts): string {
  const parts: string[] = [];
  if (present(p.role)) parts.push(p.role);
  if (present(p.grade)) parts.push(p.grade);
  const ege = [present(p.confirm) ? p.confirm : "", present(p.min_ege) ? threshold(p.min_ege) : ""]
    .filter(Boolean)
    .join(" ");
  // порог без предмета показывать нельзя: «75» без «математика» ничего не говорит
  if (ege) parts.push(`ЕГЭ ${ege}`);
  const line = parts.join(" · ");
  return line.charAt(0).toUpperCase() + line.slice(1);
}

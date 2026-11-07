import type { Metadata } from "next";
import { OlympApp } from "@/components/OlympApp";

// ссылки «Поделиться» ведут на чужие подборки — поисковикам они не нужны
export const metadata: Metadata = { robots: { index: false, follow: false } };

/** Ссылка «Поделиться» (F-01): приложение открывает экран из снимка по токену. */
export default async function SharedPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <OlympApp shareToken={token} />;
}

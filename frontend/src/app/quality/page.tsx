import type { Metadata } from "next";
import { QualityView } from "@/components/QualityView";

export const metadata: Metadata = { title: "Качество данных — Олимп" };

export default function QualityPage() {
  return <QualityView />;
}

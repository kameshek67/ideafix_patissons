import type { Metadata } from "next";
import { OpsView } from "@/components/OpsView";

export const metadata: Metadata = { title: "Оператор — Олимп", robots: { index: false, follow: false } };

export default function OpsPage() {
  return <OpsView />;
}

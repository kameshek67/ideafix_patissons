import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { Providers } from "@/components/providers";
import { MAX_BRIDGE_LOADER } from "@/lib/max";
// Onest — с нашего же адреса, а не с Google Fonts: те же файлы (переменный шрифт v11,
// совпадают побайтно), но мини-приложению MAX не нужно ходить на сторонний сервер
import "@fontsource-variable/onest";
// порядок важен: сначала компоненты прототипа, потом Tailwind — как было в index.html
import "./styles.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "Олимп — БВИ и 100 баллов по олимпиаде",
  description:
    "Двусторонний поиск льгот олимпиадников: какие олимпиады дают БВИ на выбранное направление и куда поступить с уже имеющимся дипломом.",
  icons: {
    icon: "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🎓</text></svg>",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#ffffff",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru">
      <head>
        {/* MAX Bridge — только при запуске как мини-приложение MAX (см. lib/max.ts) */}
        <script dangerouslySetInnerHTML={{ __html: MAX_BRIDGE_LOADER }} />
      </head>
      <body className="text-black antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}

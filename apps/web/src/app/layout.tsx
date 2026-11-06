import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { Providers } from "@/components/providers";
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
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        {/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <link
          href="https://fonts.googleapis.com/css2?family=Onest:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="text-black antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}

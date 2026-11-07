import type { NextConfig } from "next";

const API_URL = process.env.OLYMP_API_URL ?? "http://localhost:8000";

const config: NextConfig = {
  // Сайт и API на одном origin: Next проксирует публичные эндпоинты /v1 и Swagger.
  // Служебные /metrics, /readyz наружу не отдаём.
  async rewrites() {
    return [
      { source: "/api/v1/:path*", destination: `${API_URL}/v1/:path*` },
      { source: "/docs", destination: `${API_URL}/docs` },
      { source: "/openapi.json", destination: `${API_URL}/openapi.json` },
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
      {
        // ссылки «Поделиться»: токен не уходит на сторонние сайты в Referer и не индексируется
        source: "/s/:token",
        headers: [
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "X-Robots-Tag", value: "noindex, nofollow" },
        ],
      },
    ];
  },
  // значок Next.js в углу экрана в режиме разработки закрывал бы интерфейс
  devIndicators: false,
  transpilePackages: ["@olymp/api-client"],
};

export default config;

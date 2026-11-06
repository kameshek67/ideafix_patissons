import type { Config } from "tailwindcss";

// Та же конфигурация, что была в index.html прототипа (Tailwind 3.4.16):
// версия и токены зафиксированы, чтобы дизайн совпадал пиксель в пиксель.
export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: "#BC00F5", 600: "#A800DC", 700: "#8A00B5", 50: "#FCF5FF", 100: "#F4DCFE" },
        // льготы — оттенки фиолетового семейства, синхронно с --bvi/--sto/--alt в styles.css
        bvi: { DEFAULT: "#7300A0", bg: "#F8EBFF", line: "#EACBF8" },
        sto: { DEFAULT: "#3A2DB5", bg: "#F0EFFF", line: "#D6D2FA" },
        alt: { DEFAULT: "#9C1A61", bg: "#FFF0F7", line: "#F6CDE1" },
      },
      // VK Sans Display — шрифт макета; если не установлен, берём близкий по пропорциям Onest
      fontFamily: {
        sans: ["VK Sans Display", "Onest", "Inter", "Segoe UI", "Roboto", "Helvetica Neue", "Arial", "sans-serif"],
      },
      boxShadow: { card: "0 1px 2px rgba(16,24,40,.06), 0 1px 3px rgba(16,24,40,.10)" },
    },
  },
} satisfies Config;

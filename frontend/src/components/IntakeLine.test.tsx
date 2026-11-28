import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { IntakeLine } from "./ui";

afterEach(cleanup);

describe("IntakeLine", () => {
  it("показывает число, средний балл и источник", () => {
    render(
      <IntakeLine
        intake={{ year: 2024, olympiad_students: 624, avg_score_budget: 98.67, source: "Мониторинг эффективности вузов" }}
      />,
    );
    expect(screen.getByText(/В 2024 по олимпиадам приняли 624 человека · средний балл бюджета 98,7/)).toBeTruthy();
    expect(screen.getByText("Источник: Мониторинг эффективности вузов")).toBeTruthy();
  });

  it("без данных ничего не рисует", () => {
    const { container } = render(<IntakeLine intake={null} />);
    expect(container.textContent).toBe("");
  });
});

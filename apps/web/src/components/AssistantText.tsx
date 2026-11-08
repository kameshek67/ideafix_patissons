import { Fragment } from "react";
import { type MarkdownSpan, parseMarkdown } from "@/lib/assistant";

function Line({ spans }: { spans: MarkdownSpan[] }) {
  return (
    <>
      {spans.map((span, index) => (span.bold ? <strong key={index}>{span.text}</strong> : <Fragment key={index}>{span.text}</Fragment>))}
    </>
  );
}

function Items({ items }: { items: MarkdownSpan[][] }) {
  return (
    <>
      {items.map((item, i) => (
        <li key={i}>
          <Line spans={item} />
        </li>
      ))}
    </>
  );
}

/** Ответ помощника: абзацы, списки и жирный — React-элементами, без HTML из текста модели. */
export function AssistantText({ text }: { text: string }) {
  return (
    <div className="assistant-text space-y-2">
      {parseMarkdown(text).map((block, index) =>
        block.kind === "p" ? (
          <p key={index}>
            {block.lines.map((line, i) => (
              <Fragment key={i}>
                {i ? <br /> : null}
                <Line spans={line} />
              </Fragment>
            ))}
          </p>
        ) : block.kind === "ul" ? (
          <ul key={index} className="list-disc pl-5 space-y-1">
            <Items items={block.items} />
          </ul>
        ) : (
          <ol key={index} className="list-decimal pl-5 space-y-1">
            <Items items={block.items} />
          </ol>
        ),
      )}
    </div>
  );
}

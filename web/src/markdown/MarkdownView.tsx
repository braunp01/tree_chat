// Markdown rendering for assistant Messages (Req 2.6): parsed to mdast and rendered by our own component, so raw HTML
// is never injected.
import { Fragment, type ComponentChildren, type JSX } from "preact";
import { fromMarkdown } from "mdast-util-from-markdown";
import { gfmFromMarkdown } from "mdast-util-gfm";
import { gfm } from "micromark-extension-gfm";
import type { Nodes, Parents, Root, TableRow } from "mdast";

export function parseMarkdown(source: string): Root {
  return fromMarkdown(source, { extensions: [gfm()], mdastExtensions: [gfmFromMarkdown()] });
}

type Kind = "text" | "inlineCode" | "code" | "raw";

function mapped(value: string, _node: Nodes, _kind: Kind, key?: number): JSX.Element {
  return <Fragment key={key}>{value}</Fragment>;
}

function children(node: Parents): ComponentChildren {
  return node.children.map((c, i) => renderNode(c as Nodes, i));
}

function renderRow(row: TableRow, header: boolean, i: number): JSX.Element {
  return (
    <tr key={i}>
      {row.children.map((cell, j) => (header ? <th key={j}>{children(cell)}</th> : <td key={j}>{children(cell)}</td>))}
    </tr>
  );
}

function renderNode(node: Nodes, key?: number): JSX.Element | null {
  switch (node.type) {
    case "root":
      return <>{children(node)}</>;
    case "paragraph":
      return <p key={key}>{children(node)}</p>;
    case "heading": {
      const H = `h${node.depth}` as "h1";
      return <H key={key}>{children(node)}</H>;
    }
    case "text":
      return mapped(node.value, node, "text", key);
    case "emphasis":
      return <em key={key}>{children(node)}</em>;
    case "strong":
      return <strong key={key}>{children(node)}</strong>;
    case "delete":
      return <del key={key}>{children(node)}</del>;
    case "inlineCode":
      return <code key={key}>{mapped(node.value, node, "inlineCode")}</code>;
    case "code":
      return (
        <pre key={key}>
          <code>{mapped(node.value, node, "code")}</code>
        </pre>
      );
    case "blockquote":
      return <blockquote key={key}>{children(node)}</blockquote>;
    case "list":
      return node.ordered ? (
        <ol key={key} start={node.start ?? 1}>
          {children(node)}
        </ol>
      ) : (
        <ul key={key}>{children(node)}</ul>
      );
    case "listItem":
      return <li key={key}>{children(node)}</li>;
    case "table":
      return (
        <table key={key}>
          <thead>{node.children[0] && renderRow(node.children[0], true, 0)}</thead>
          <tbody>{node.children.slice(1).map((r, i) => renderRow(r, false, i))}</tbody>
        </table>
      );
    case "link":
      return (
        <a key={key} href={node.url} target="_blank" rel="noreferrer noopener">
          {children(node)}
        </a>
      );
    case "break":
      return <br key={key} />;
    case "thematicBreak":
      return <hr key={key} />;
    case "html":
      // Raw HTML is shown as text, never injected.
      return mapped(node.value, node, "raw", key);
    case "image":
    case "imageReference":
    case "definition":
    case "footnoteDefinition":
    case "yaml":
      return null;
    default:
      return "children" in node ? <>{children(node as Parents)}</> : null;
  }
}

export function MarkdownView({ source }: { source: string }): JSX.Element {
  return <div class="md">{renderNode(parseMarkdown(source))}</div>;
}

/** User Messages are shown as typed (Req 2.6). */
export function PlainView({ source }: { source: string }): JSX.Element {
  return <div class="plain">{source}</div>;
}

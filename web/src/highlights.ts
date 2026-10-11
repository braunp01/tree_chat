// Character-exact marking of anchored passages through the CSS Custom Highlight API (Req 5.1, 5.2). Where the browser
// lacks it, callers fall back to marking whole rendered runs.
type Registry = Map<string, Map<object, Range[]>>;
const registry: Registry = new Map();

interface HighlightLike {
  priority: number;
}
interface HighlightsApi {
  set(name: string, h: HighlightLike): void;
  delete(name: string): void;
}

function api(): { highlights: HighlightsApi; make: (ranges: Range[]) => HighlightLike } | null {
  const css = (globalThis as { CSS?: { highlights?: HighlightsApi } }).CSS;
  const H = (globalThis as { Highlight?: new (...r: Range[]) => HighlightLike }).Highlight;
  if (!css?.highlights || !H) return null;
  return { highlights: css.highlights, make: (r) => new H(...r) };
}

export const highlightsSupported = (): boolean => api() !== null;

const PRIORITY: Record<string, number> = { "anchor-closed": 1, "anchor-parked": 2, "anchor-open": 3, "anchor-hover": 10 };

/** Replace what `owner` (one Message) contributes to the named highlight. */
export function setHighlight(name: string, owner: object, ranges: Range[]): void {
  const a = api();
  if (!a) return;
  const byOwner = registry.get(name) ?? new Map<object, Range[]>();
  if (ranges.length) byOwner.set(owner, ranges);
  else byOwner.delete(owner);
  registry.set(name, byOwner);
  const all = [...byOwner.values()].flat();
  if (all.length === 0) a.highlights.delete(name);
  else {
    const h = a.make(all);
    h.priority = PRIORITY[name] ?? 0;
    a.highlights.set(name, h);
  }
}

export function clearOwner(owner: object): void {
  for (const name of registry.keys()) setHighlight(name, owner, []);
}

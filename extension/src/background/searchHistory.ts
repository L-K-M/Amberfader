import type { SearchHistory } from "../protocol/types";

export const RECENT_ITEMS_CAP = 20;
const MAX_ITEM_LENGTH = 500;
const STORAGE_KEY = "searchHistory";

function normalizedItems(value: unknown): string[] {
  if (!Array.isArray(value)) return [];

  const seen = new Set<string>();
  const items: string[] = [];
  for (const raw of value) {
    if (typeof raw !== "string") continue;

    const item = raw.replace(/\p{Cc}/gu, " ").trim().slice(0, MAX_ITEM_LENGTH);
    const key = item.toLowerCase();
    if (!item || seen.has(key)) continue;

    seen.add(key);
    items.push(item);
    if (items.length === RECENT_ITEMS_CAP) break;
  }
  return items;
}

// The router owns shared history for both UIs. Serialize storage operations so
// a query, track update, or clear cannot overwrite a concurrent change.
export class SearchHistoryService {
  private tail: Promise<void> = Promise.resolve();

  get(): Promise<SearchHistory> {
    return this.enqueue();
  }

  recordQuery(query: string): Promise<SearchHistory> {
    return this.enqueue((history) => ({
      ...history, queries: normalizedItems([query, ...history.queries]),
    }));
  }

  recordArtists(artists: string[]): Promise<SearchHistory> {
    return this.enqueue((history) => ({
      ...history, artists: normalizedItems([...artists, ...history.artists]),
    }));
  }

  clear(): Promise<SearchHistory> {
    return this.enqueue(() => ({ queries: [], artists: [] }));
  }

  private enqueue(update?: (history: SearchHistory) => SearchHistory): Promise<SearchHistory> {
    const operation = this.tail.then(async () => {
      const stored = (await browser.storage.local.get(STORAGE_KEY)) as Record<string, unknown>;
      const raw = stored[STORAGE_KEY] as Partial<SearchHistory> | null | undefined;
      const history = {
        queries: normalizedItems(raw?.queries), artists: normalizedItems(raw?.artists),
      };
      if (!update) return history;

      const next = update(history);
      await browser.storage.local.set({ [STORAGE_KEY]: next });
      return next;
    });
    // A storage failure is reported to the caller without poisoning later work.
    this.tail = operation.then(() => undefined, () => undefined);
    return operation;
  }
}

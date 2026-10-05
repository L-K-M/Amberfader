// Removes ad data from YouTube Music's player responses, the technique
// uBlock Origin's own filters use on music.youtube.com (uAssets
// filters/filters.txt: `set ytInitialPlayerResponse.adPlacements undefined`
// and `json-prune playerResponse.adPlacements playerResponse.playerAds
// playerResponse.adSlots adPlacements playerAds adSlots`).
//
// Runs in the page's main world, before the page's own scripts. It holds no
// reference to Amberfader's bridge and sends nothing anywhere.
export const AD_KEYS = ["adPlacements", "playerAds", "adSlots"] as const;
const GLOBALS = ["ytInitialPlayerResponse", "playerResponse"] as const;
const INSTALLED = Symbol.for("amberfader.adFilter");

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function dropAdKeys(target: Record<string, unknown>): void {
  for (const key of AD_KEYS) {
    if (Object.prototype.hasOwnProperty.call(target, key)) delete target[key];
  }
}

// Mutates and returns `value`: ad keys at the top level and under
// `playerResponse` are removed. Anything else passes through untouched.
export function stripAds<T>(value: T): T {
  if (!isRecord(value)) return value;
  dropAdKeys(value);
  const response = value.playerResponse;
  if (isRecord(response)) dropAdKeys(response);
  return value;
}

type FilterWindow = typeof globalThis & { [INSTALLED]?: true } & Record<string, unknown>;

export function installAdFilter(win: typeof globalThis): void {
  const target = win as FilterWindow;
  if (target[INSTALLED]) return;
  Object.defineProperty(target, INSTALLED, { value: true });

  // A Proxy keeps JSON.parse's native toString and arity.
  target.JSON.parse = new Proxy(target.JSON.parse, {
    apply: (parse, thisArg, args: unknown[]): unknown =>
      stripAds(Reflect.apply(parse, thisArg, args) as unknown),
  });

  // Inline page scripts assign these globals directly instead of parsing.
  for (const name of GLOBALS) {
    let current: unknown = stripAds(target[name]);
    Object.defineProperty(target, name, {
      configurable: true,
      enumerable: true,
      get: () => current,
      set: (next: unknown) => {
        current = stripAds(next);
      },
    });
  }
}

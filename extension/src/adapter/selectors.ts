// YouTube Music selector configuration.
//
// EVERY selector and label pattern in this file is UNVERIFIED until the
// Phase 0 probe suite has been run on a live session (docs/manual-test-plan.md).
// They encode the page structure as of writing, based on documented component
// names; treat them as candidates the probes must confirm, not as truth.
// Feature-detect each capability before use — a missing control must only
// disable its own capability.

export interface ControlQuery {
  // Candidate CSS selectors for the control element, most-preferred first.
  selectors: string[];
  // Accessible-label fallback patterns. English only — other locales land
  // here once the probe has captured them on a non-English account.
  ariaLabels: RegExp[];
}

export const PLAYER_ROOT_SELECTORS = [
  "ytmusic-player-bar",
  "ytmusic-app[player-page-open_]",
  "ytmusic-app",
];

export const MEDIA_ELEMENT_SELECTOR = "video";

export const TRACK_INFO = {
  title: [
    "ytmusic-player-bar .title",
    "ytmusic-player-bar .content-info-wrapper .title",
  ],
  byline: [
    "ytmusic-player-bar .byline",
    "ytmusic-player-bar .subtitle .byline",
  ],
  artwork: ["ytmusic-player-bar img.image", "ytmusic-player-bar img#img"],
};

export const CONTROLS: Record<string, ControlQuery> = {
  playPause: {
    selectors: [
      "ytmusic-player-bar #play-pause-button",
      "#play-pause-button",
      "tp-yt-paper-icon-button#play-pause-button",
    ],
    ariaLabels: [/^play$/i, /^pause$/i],
  },
  previous: {
    selectors: [
      "ytmusic-player-bar .previous-button",
      "ytmusic-player-bar tp-yt-paper-icon-button[title*='revious' i]",
    ],
    ariaLabels: [/previous/i],
  },
  next: {
    selectors: [
      "ytmusic-player-bar .next-button",
      "ytmusic-player-bar tp-yt-paper-icon-button[title*='ext' i]",
    ],
    ariaLabels: [/next/i],
  },
};

export const SEARCH = {
  input: [
    "ytmusic-search-box input",
    "ytmusic-search-box input[placeholder]",
    "input[type='search']",
  ],
  searchBox: ["ytmusic-search-box"],
  resultsRoot: [
    "ytmusic-search-page",
    "ytmusic-section-list-renderer",
    "ytmusic-tabbed-search-results-renderer",
  ],
  resultRow: [
    "ytmusic-responsive-list-item-renderer",
    "ytmusic-shelf-renderer ytmusic-responsive-list-item-renderer",
  ],
  rowTitle: [".title", "yt-formatted-string.title", ".title a"],
  rowSubtitle: [".subtitle", ".secondary-flex-columns", ".byline"],
  rowThumbnail: ["img"],
  rowPlayButton: [
    "ytmusic-play-button-renderer",
    "ytmusic-responsive-list-item-renderer .play-button",
    "ytmusic-responsive-list-item-renderer ytmusic-play-button-renderer",
  ],
};

// aria-label/state attributes worth probing. UNVERIFIED until Phase 0.
export const ARIA_STATE_ATTRS = ["aria-label", "title", "aria-pressed"];

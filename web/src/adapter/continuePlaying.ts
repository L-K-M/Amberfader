// "Continue playing": closes YouTube Music's "Video paused. Continue
// watching?" prompt and resumes playback, the job the YouTube NonStop
// extension does in a browser. Amberfader's page never sees user input, so
// YouTube Music always considers it idle.
//
// It acts only while that specific prompt is visible, and never on other
// popups. The prompt's selectors are UNVERIFIED (see selectors.ts).
import { MEDIA_ELEMENT_SELECTOR, YOU_THERE } from "./selectors";
import { isVisibleControl } from "./dom";

export class ContinuePlaying {
  private started = false;

  constructor(private readonly doc: Document) {}

  start(): void {
    if (this.started) return;
    this.started = true;
    this.doc.addEventListener(YOU_THERE.openedEvent, this.check);
    // Media events do not bubble; capture sees the pause the prompt causes.
    this.doc.addEventListener("pause", this.check, true);
  }

  stop(): void {
    if (!this.started) return;
    this.started = false;
    this.doc.removeEventListener(YOU_THERE.openedEvent, this.check);
    this.doc.removeEventListener("pause", this.check, true);
  }

  // Returns whether a visible prompt was found and dismissed.
  readonly check = (): boolean => {
    const prompt = this.doc.querySelector(YOU_THERE.prompt);
    if (!prompt || !isVisibleControl(prompt)) return false;
    const container = prompt.closest(YOU_THERE.container);
    if (!(container instanceof HTMLElement)) return false;

    container.click();
    const media = this.doc.querySelector(MEDIA_ELEMENT_SELECTOR);
    if (media instanceof HTMLMediaElement && media.paused) {
      // A rejected play() leaves the track paused, which the player then
      // reports as paused; nothing claims it resumed.
      void media.play().catch(() => undefined);
    }
    return true;
  };
}

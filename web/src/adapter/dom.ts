// Site controls can exist in several hidden player bars or cached menus.
// Layout visibility, not document visibility, also works for a hidden tab.
export function isVisibleControl(element: Element): element is HTMLElement {
  if (!(element instanceof HTMLElement) || !element.isConnected ||
      element.getClientRects().length === 0) return false;

  for (let node: HTMLElement | null = element; node; node = node.parentElement) {
    if (node.hidden || node.hasAttribute("inert") || node.getAttribute("aria-hidden") === "true") return false;

    const style = getComputedStyle(node);
    if (style.display === "none" || style.visibility === "hidden" || style.visibility === "collapse") return false;
  }
  return true;
}

export function isEnabledControl(element: HTMLElement): boolean {
  return !element.hasAttribute("disabled") && element.getAttribute("aria-disabled") !== "true";
}

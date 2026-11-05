/**
 * Place a deadline calendar outside scroll-clipped modal content.
 *
 * Prefer the side of the trigger with enough room. If neither side can show
 * the full calendar, limit its height and let the calendar itself scroll.
 * All coordinates use the visible viewport (including mobile keyboard offsets).
 */
export function positionDeadlinePopover(trigger, popover, viewport) {
  const margin = 12;
  const gap = 8;
  const top = viewport.top + margin;
  const bottom = viewport.top + viewport.height - margin;
  const left = viewport.left + margin;
  const right = viewport.left + viewport.width - margin;
  const spaceAbove = Math.max(0, trigger.top - top - gap);
  const spaceBelow = Math.max(0, bottom - trigger.bottom - gap);
  const above = spaceBelow < popover.height && spaceAbove > spaceBelow;
  const availableSpace = above ? spaceAbove : spaceBelow;
  const viewportHeight = Math.max(0, viewport.height - margin * 2);

  // When neither side has a usable calendar area, show a viewport-contained
  // floating panel rather than a tiny, unusable anchored dropdown.
  const floatInViewport = availableSpace < Math.min(280, popover.height);
  const maxHeight = floatInViewport
    ? viewportHeight
    : Math.min(viewportHeight, availableSpace, popover.height);
  const height = Math.min(popover.height, maxHeight);
  const width = Math.min(popover.width, Math.max(0, right - left));
  const desiredTop = floatInViewport
    ? top + Math.max(0, (viewportHeight - height) / 2)
    : above
      ? trigger.top - gap - height
      : trigger.bottom + gap;

  return {
    top: Math.max(top, Math.min(desiredTop, bottom - height)),
    left: Math.max(left, Math.min(trigger.left, right - width)),
    maxHeight,
    width,
  };
}

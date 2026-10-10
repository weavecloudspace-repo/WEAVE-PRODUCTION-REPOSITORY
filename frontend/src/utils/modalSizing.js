export function modalWidthClass(className = "") {
  // Base width utilities conflict by stylesheet order, not class-list order.
  // Responsive utilities can safely override the default at their breakpoint.
  return className.split(/\s+/).some((token) => /^!?max-w-/.test(token))
    ? ""
    : "max-w-lg";
}

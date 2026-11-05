import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import Button from "../../components/ui/Button";
import Dropdown from "../../components/ui/Dropdown";

export default function TmaActions({ items, busy }) {
  const [open, setOpen] = useState(false);
  const root = useRef(null);
  const trigger = useRef(null);
  useEffect(() => {
    if (open) root.current?.querySelector('[role="menuitem"]')?.focus();
  }, [open]);
  return (
    <Dropdown
      open={open}
      onOpenChange={setOpen}
      trigger={
        <Button disabled={busy} aria-haspopup="menu" aria-expanded={open}>
          <span ref={trigger} tabIndex={-1}>
            Actions
          </span>
          <ChevronDown className="h-4 w-4" />
        </Button>
      }
    >
      <div
        ref={root}
        role="menu"
        aria-label="Assignment actions"
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.preventDefault();
            setOpen(false);
            trigger.current?.closest("button")?.focus();
          }
          const buttons = [
            ...e.currentTarget.querySelectorAll('[role="menuitem"]'),
          ];
          const index = buttons.indexOf(document.activeElement);
          if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) {
            e.preventDefault();
            const next =
              e.key === "Home"
                ? 0
                : e.key === "End"
                  ? buttons.length - 1
                  : (index +
                      (e.key === "ArrowDown" ? 1 : -1) +
                      buttons.length) %
                    buttons.length;
            buttons[next]?.focus();
          }
        }}
      >
        {items
          .filter((item) => item.visible !== false)
          .map(({ label, icon: Icon, onClick, danger, disabled, reason }) => (
            <button
              key={label}
              role="menuitem"
              type="button"
              disabled={disabled}
              aria-disabled={disabled}
              title={disabled ? reason : undefined}
              className={`flex min-h-11 w-full items-center gap-3 rounded-xl px-3 text-left text-sm transition hover:bg-surface-muted focus:bg-surface-muted focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 ${danger ? "text-error" : "text-text"}`}
              onClick={() => {
                setOpen(false);
                onClick();
              }}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {label}
            </button>
          ))}
      </div>
    </Dropdown>
  );
}

import { useEffect, useRef, useState } from "react";
import { CheckCheck, FilePenLine, LockKeyhole, MoreHorizontal, RotateCcw, Send } from "lucide-react";

import Button from "../../components/ui/Button";
import Dropdown from "../../components/ui/Dropdown";
import { resultLifecycleOptions } from "./resultLifecycleOptions";

const icons = {
  edit: FilePenLine,
  submitted: Send,
  approved: CheckCheck,
  locked: LockKeyhole,
  return_to_draft: RotateCcw,
};

export default function ResultLifecycleMenu({
  item,
  periodEditable,
  busy,
  onEdit,
  onTransition,
  onReturnToDraft,
}) {
  const [open, setOpen] = useState(false);
  const triggerContent = useRef(null);
  const menuRef = useRef(null);
  const options = resultLifecycleOptions(item.status);

  useEffect(() => {
    if (open) menuRef.current?.querySelector('[role="menuitem"]:not([disabled])')?.focus();
  }, [open]);

  const handleSelect = (key) => {
    setOpen(false);
    if (key === "edit") onEdit();
    else if (key === "return_to_draft") onReturnToDraft();
    else onTransition(key);
  };

  if (!options.length) return null;

  return (
    <Dropdown
      strategy="fixed"
      align="right"
      open={open}
      onOpenChange={setOpen}
      trigger={
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="h-9 w-9 min-h-9 shrink-0 rounded-xl"
          aria-label={`Manage result for ${item.student_name || item.admission_number || "student"}`}
          aria-haspopup="menu"
          aria-expanded={open}
          disabled={busy}
        >
          <span ref={triggerContent}>
            <MoreHorizontal className="h-5 w-5" aria-hidden="true" />
          </span>
        </Button>
      }
    >
      <div
        ref={menuRef}
        role="menu"
        aria-label={`Result lifecycle actions for ${item.student_name || "student"}`}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            setOpen(false);
            triggerContent.current?.closest("button")?.focus();
            return;
          }
          const choices = [...event.currentTarget.querySelectorAll('[role="menuitem"]:not([disabled])')];
          const current = choices.indexOf(document.activeElement);
          if (!choices.length) return;
          if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
            event.preventDefault();
            const next = event.key === "Home" ? 0
              : event.key === "End" ? choices.length - 1
                : (current + (event.key === "ArrowDown" ? 1 : -1) + choices.length) % choices.length;
            choices[next]?.focus();
          }
        }}
      >
        <div className="px-3 pb-2 pt-1">
          <p className="text-xs font-semibold text-text">Manage result</p>
          <p className="mt-1 text-[11px] text-text-muted">Current status: {item.status}</p>
        </div>
        <div className="border-t border-border/60 pt-1">
          {options.map(({ key, label }) => {
            const Icon = icons[key];
            return (
              <button
                key={key}
                type="button"
                role="menuitem"
                disabled={!periodEditable || busy}
                title={!periodEditable ? "Only available in the current open session and term." : undefined}
                onClick={() => handleSelect(key)}
                className="flex min-h-11 w-full items-center gap-3 rounded-xl px-3 text-left text-sm font-medium text-text transition hover:bg-surface-muted focus-visible:bg-surface-muted focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Icon className="h-4 w-4 shrink-0 text-text-muted" aria-hidden="true" />
                {label}
              </button>
            );
          })}
        </div>
        {!periodEditable && (
          <p className="border-t border-border/60 px-3 py-2 text-xs text-text-muted">
            Changes are unavailable outside the current open session and term.
          </p>
        )}
      </div>
    </Dropdown>
  );
}

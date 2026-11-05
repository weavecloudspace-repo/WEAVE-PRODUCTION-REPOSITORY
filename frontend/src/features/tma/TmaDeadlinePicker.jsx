import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CalendarDays, ChevronLeft, ChevronRight, Clock3 } from "lucide-react";
import "./tma-deadline-picker.css";
import { positionDeadlinePopover } from "./deadlinePopoverPosition";

const days = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];
const pad = (n) => String(n).padStart(2, "0");
const initialMonth = (value) => {
  const match = /^(\d{4})-(\d{2})-/.exec(value || "");
  if (match) return { year: Number(match[1]), month: Number(match[2]) - 1 };
  const today = new Date();
  return { year: today.getFullYear(), month: today.getMonth() };
};
const formatDeadlineLocal = (year, month, day, hour, minute) =>
  `${year}-${pad(month + 1)}-${pad(day)}T${pad(hour)}:${pad(minute)}`;

export default function TmaDeadlinePicker({ value, onChange, disabled = false, invalid = false }) {
  const [opened, setOpened] = useState(false);
  const [display, setDisplay] = useState(() => initialMonth(value));
  const [placement, setPlacement] = useState(null);
  const [portalHost, setPortalHost] = useState(null);
  const container = useRef(null);
  const popover = useRef(null);
  const day = value ? Number(value.slice(8, 10)) : null;
  const hour = value ? Number(value.slice(11, 13)) : 17;
  const minute = value ? Number(value.slice(14, 16)) : 0;
  const selectedDate = value?.slice(0, 10) || "";
  const date = selectedDate ? new Date(`${selectedDate}T12:00:00`) : null;
  const summary = date && !Number.isNaN(date.getTime())
    ? `${date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })} · ${pad(hour)}:${pad(minute)}`
    : "Choose date and time";
  useEffect(() => {
    if (!opened) return undefined;
    const handle = (event) => {
      if (event.type === "keydown" && event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation(); // Keep Escape from also dismissing the parent modal.
        setOpened(false);
        container.current?.querySelector(".tma-deadline-trigger")?.focus();
      } else if (event.type === "pointerdown"
        && !container.current?.contains(event.target)
        && !popover.current?.contains(event.target)) {
        setOpened(false);
      }
    };
    document.addEventListener("pointerdown", handle);
    document.addEventListener("keydown", handle);
    return () => {
      document.removeEventListener("pointerdown", handle);
      document.removeEventListener("keydown", handle);
    };
  }, [opened]);
  // The portal host is resolved in the trigger event handler; never read
  // refs while React is rendering.
  const host = opened ? portalHost : null;

  useLayoutEffect(() => {
    if (!opened) return undefined;
    const position = () => {
      const trigger = container.current?.querySelector(".tma-deadline-trigger");
      const calendar = popover.current;
      if (!trigger || !calendar) return;
      const rect = trigger.getBoundingClientRect();
      const visual = window.visualViewport;
      const next = positionDeadlinePopover(
        { top: rect.top, bottom: rect.bottom, left: rect.left },
        { width: 342, height: calendar.scrollHeight },
        {
          top: visual?.offsetTop ?? 0,
          left: visual?.offsetLeft ?? 0,
          width: visual?.width ?? window.innerWidth,
          height: visual?.height ?? window.innerHeight,
        },
      );
      setPlacement((previous) => previous
        && previous.top === next.top && previous.left === next.left
        && previous.maxHeight === next.maxHeight && previous.width === next.width
        ? previous : next);
    };
    position();
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(position) : null;
    if (popover.current) observer?.observe(popover.current);
    document.addEventListener("scroll", position, true);
    window.addEventListener("resize", position);
    window.visualViewport?.addEventListener("resize", position);
    window.visualViewport?.addEventListener("scroll", position);
    return () => {
      observer?.disconnect();
      document.removeEventListener("scroll", position, true);
      window.removeEventListener("resize", position);
      window.visualViewport?.removeEventListener("resize", position);
      window.visualViewport?.removeEventListener("scroll", position);
    };
  }, [opened]);

  const setTime = (nextHour, nextMinute) => {
    const picked = day ? new Date(`${selectedDate}T12:00:00`) : new Date();
    const y = picked.getFullYear();
    const m = picked.getMonth();
    const d = day || picked.getDate();
    onChange(formatDeadlineLocal(y, m, d, nextHour, nextMinute));
  };
  const firstDay = new Date(display.year, display.month, 1).getDay();
  const count = new Date(display.year, display.month + 1, 0).getDate();
  const cells = Array.from({ length: Math.ceil((firstDay + count) / 7) * 7 }, (_, index) =>
    index - firstDay + 1);
  const shift = (delta) => {
    const updated = new Date(display.year, display.month + delta, 1);
    setDisplay({ year: updated.getFullYear(), month: updated.getMonth() });
  };
  return <div ref={container} className="tma-deadline-picker">
    <button type="button" className="tma-deadline-trigger" aria-label="Choose submission deadline"
      aria-haspopup="dialog" aria-expanded={opened} aria-invalid={invalid}
      disabled={disabled} onClick={() => {
        setDisplay(initialMonth(value));
        setPlacement(null);
        if (!opened) {
          setPortalHost(container.current?.closest('[data-modal-overlay="true"]') || document.body);
        }
        setOpened((old) => !old);
      }}>
      <CalendarDays size={18} aria-hidden="true" />
      <span>{summary}</span>
      <Clock3 size={17} aria-hidden="true" />
    </button>
    {opened && host && createPortal(<div ref={popover} data-modal-popover="true"
      className="tma-deadline-popover" role="dialog" aria-label="Submission deadline calendar"
      style={{ top: placement?.top ?? 0, left: placement?.left ?? 0,
        maxHeight: placement?.maxHeight, width: placement?.width,
        visibility: placement ? "visible" : "hidden" }}
      onClick={(event) => event.stopPropagation()}>
      <div className="tma-deadline-month">
        <button type="button" aria-label="Previous month" onClick={() => shift(-1)}><ChevronLeft size={18} /></button>
        <strong>{new Date(display.year, display.month, 1).toLocaleDateString(undefined, { month: "long", year: "numeric" })}</strong>
        <button type="button" aria-label="Next month" onClick={() => shift(1)}><ChevronRight size={18} /></button>
      </div>
      <div className="tma-deadline-grid" role="group" aria-label="Calendar days">
        {days.map((label) => <span className="tma-deadline-weekday" key={label}>{label}</span>)}
        {cells.map((number, index) => number > 0 && number <= count
          ? <button type="button" key={index} className={selectedDate === `${display.year}-${pad(display.month + 1)}-${pad(number)}` ? "is-selected" : ""}
              aria-label={new Date(display.year, display.month, number).toDateString()}
              aria-pressed={selectedDate === `${display.year}-${pad(display.month + 1)}-${pad(number)}`}
              onClick={() => onChange(formatDeadlineLocal(display.year, display.month, number, hour, minute))}>{number}</button>
          : <span key={index} />)}
      </div>
      <div className="tma-deadline-time">
        <label>Hour <select aria-label="Deadline hour" value={hour}
          onChange={(e) => setTime(Number(e.target.value), minute)}>
          {Array.from({ length: 24 }, (_, i) => <option value={i} key={i}>{pad(i)}</option>)}
        </select></label>
        <span>:</span>
        <label>Minute <select aria-label="Deadline minute" value={minute}
          onChange={(e) => setTime(hour, Number(e.target.value))}>
          {Array.from({ length: 60 }, (_, i) => <option value={i} key={i}>{pad(i)}</option>)}
        </select></label>
      </div>
      <button type="button" className="tma-deadline-done" onClick={() => setOpened(false)}>Done</button>
    </div>, host)}
  </div>;
}

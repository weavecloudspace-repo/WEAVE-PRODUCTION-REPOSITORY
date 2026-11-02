import { useEffect, useRef, useState } from "react";
import "./tma-authoring.css";

// Adapted from CBT's QuestionAuthoringWorkspace: resize only this workspace,
// keeping the dashboard shell, drawer and bottom navigation untouched.
export default function TmaAuthoringWorkspace({ children, panel, open }) {
  const root = useRef(null);
  const drag = useRef(null);
  const [width, setWidth] = useState(380);
  const [available, setAvailable] = useState(1100);
  const [height, setHeight] = useState(600);
  const maximum = Math.max(300, Math.min(520, Math.floor(available * 0.45)));
  const actual = Math.min(width, maximum);
  useEffect(() => {
    if (!root.current || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) =>
      setAvailable(entry.contentRect.width),
    );
    observer.observe(root.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!open || !root.current) return;
    const viewport = root.current.closest("#dashboard-scroll-viewport");
    if (!viewport) return;
    const measure = () => {
      const top = root.current.getBoundingClientRect().top
        - viewport.getBoundingClientRect().top + viewport.scrollTop;
      setHeight(Math.max(240, viewport.clientHeight - top));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, [open]);
  const resize = (next) => setWidth(Math.max(300, Math.min(maximum, next)));
  return (
    <div
      ref={root}
      className={`tma-workspace ${open ? "tma-workspace--ai" : ""}`}
      style={{ "--tma-ai-width": `${actual}px`, "--tma-workspace-height": `${height}px` }}
    >
      <div className="tma-workspace-content">{children}</div>
      {open && (
        <div
          className="tma-workspace-divider"
          role="separator"
          tabIndex={0}
          aria-label="Resize AI panel"
          aria-orientation="vertical"
          aria-valuemin={300}
          aria-valuemax={maximum}
          aria-valuenow={actual}
          onPointerDown={(e) => {
            if (e.button !== 0) return;
            e.preventDefault();
            e.currentTarget.setPointerCapture(e.pointerId);
            drag.current = { x: e.clientX, width: actual };
          }}
          onPointerMove={(e) => {
            if (drag.current)
              resize(drag.current.width + drag.current.x - e.clientX);
          }}
          onPointerUp={() => {
            drag.current = null;
          }}
          onPointerCancel={() => {
            drag.current = null;
          }}
          onLostPointerCapture={() => {
            drag.current = null;
          }}
          onKeyDown={(e) => {
            if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) {
              e.preventDefault();
              resize(
                e.key === "Home"
                  ? 300
                  : e.key === "End"
                    ? maximum
                    : actual + (e.key === "ArrowLeft" ? 20 : -20),
              );
            }
          }}
          onDoubleClick={() => resize(380)}
        />
      )}
      <div className="tma-workspace-panel" hidden={!open}>
        {panel}
      </div>
    </div>
  );
}

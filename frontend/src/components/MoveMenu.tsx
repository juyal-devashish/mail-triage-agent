import { useEffect, useRef, useState } from "react";
import { BUCKET_LABEL, type Bucket, type Item, type RuleScope } from "../types";

const BUCKETS: Bucket[] = ["needs_you", "fyi", "noise"];

interface Props {
  item: Item;
  onMove: (bucket: Bucket, scope: RuleScope) => void;
}

/** "Wrong call?" menu: move one email to another bucket, and by default remember it for the sender. */
export function MoveMenu({ item, onMove }: Props) {
  const [open, setOpen] = useState(false);
  const [remember, setRemember] = useState(true);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  return (
    <div className="move" ref={ref}>
      <button
        className="btn ghost"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
        title="Wrong call? Move it"
      >
        Move
      </button>
      {open && (
        <div className="menu" role="menu" onClick={(e) => e.stopPropagation()}>
          <div className="menu-title">Move to</div>
          {BUCKETS.filter((b) => b !== item.bucket).map((b) => (
            <button
              key={b}
              role="menuitem"
              className={`menu-item dot-${b}`}
              onClick={() => {
                setOpen(false);
                onMove(b, remember ? "sender" : "none");
              }}
            >
              {BUCKET_LABEL[b]}
            </button>
          ))}
          <label className="menu-check">
            <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
            <span>
              Always for <strong>{item.from_email}</strong>
            </span>
          </label>
        </div>
      )}
    </div>
  );
}

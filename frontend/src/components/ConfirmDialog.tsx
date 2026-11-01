import { useEffect, useRef, type ReactNode } from "react";

interface Props {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Native <dialog>: focus trapping and Escape-to-close come from the browser. */
export function ConfirmDialog({ open, title, children, confirmLabel, danger, busy, onConfirm, onCancel }: Props) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className="dialog"
      aria-labelledby="dialog-title"
      onCancel={(e) => {
        e.preventDefault();
        onCancel();
      }}
    >
      <h2 id="dialog-title" className="panel-title">
        {title}
      </h2>
      <div className="dialog-body">{children}</div>
      <div className="dialog-actions">
        <button type="button" className="btn" onClick={onCancel} autoFocus>
          Cancel
        </button>
        <button
          type="button"
          className={danger ? "btn btn-danger-solid" : "btn btn-primary"}
          onClick={onConfirm}
          disabled={busy}
        >
          {confirmLabel}
        </button>
      </div>
    </dialog>
  );
}

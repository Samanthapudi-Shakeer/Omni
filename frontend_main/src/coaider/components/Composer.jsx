import React, { useEffect, useRef } from 'react';

export default function Composer({ value, onChange, onSend, disabled, statusLabel }) {
  const textareaRef = useRef(null);

  function autoGrow() {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 160) + 'px';
  }

  useEffect(() => { autoGrow(); }, [value]);

  function submit(e) {
    e.preventDefault();
    if (disabled) return;
    const trimmed = value.trim();
    if (!trimmed) return;
    onSend(trimmed);
  }

  return (
    <form className="composer" onSubmit={submit}>
      <textarea
        ref={textareaRef}
        rows={1}
        placeholder={
          disabled
            ? `Aider is ${statusLabel || 'busy'} — send disabled until it finishes…`
            : 'Ask Aider anything about this workspace…  (Shift+Enter for newline, Ctrl+K for commands)'
        }
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            submit(e);
          }
        }}
      />
      <button type="submit" className="btn primary" disabled={disabled || !value.trim()}>
        {disabled ? 'Working…' : 'Send'}
      </button>
    </form>
  );
}

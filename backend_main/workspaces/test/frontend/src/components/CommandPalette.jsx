import React, { useEffect, useMemo, useRef, useState } from 'react';

export default function CommandPalette({ open, commands, onClose, onExecute, onInsert }) {
  const [query, setQuery] = useState('');
  const inputRef = useRef(null);

  useEffect(() => {
    if (open) {
      setQuery('');
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter(
      (c) => c.cmd.toLowerCase().includes(q) || c.desc.toLowerCase().includes(q)
    );
  }, [query, commands]);

  if (!open) return null;

  function choose(c) {
    if (c.immediate) {
      onExecute(c.cmd);
    } else {
      onInsert(c.args ? `${c.cmd} ` : c.cmd);
    }
    onClose();
  }

  return (
    <div className="palette-overlay" onClick={onClose}>
      <div className="palette" onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          className="palette-input"
          placeholder="Search Aider commands…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') onClose();
            if (e.key === 'Enter' && filtered.length > 0) choose(filtered[0]);
          }}
        />
        <div className="palette-list">
          {filtered.length === 0 && <div className="palette-empty">No matching commands.</div>}
          {filtered.map((c) => (
            <button key={c.cmd} className="palette-item" onClick={() => choose(c)} type="button">
              <span className="palette-cmd mono">{c.cmd} {c.args && <span className="dim">{c.args}</span>}</span>
              <span className="palette-desc">{c.desc}</span>
            </button>
          ))}
        </div>
        <div className="palette-hint">Enter to run/insert · Esc to close</div>
      </div>
    </div>
  );
}

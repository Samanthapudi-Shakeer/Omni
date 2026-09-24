import React, { useEffect, useState } from 'react';

export default function SaveFileModal({ open, defaultPath, onCancel, onConfirm }) {
  const [path, setPath] = useState(defaultPath || '');

  useEffect(() => { if (open) setPath(defaultPath || ''); }, [open, defaultPath]);

  if (!open) return null;

  function submit(e) {
    e.preventDefault();
    if (!path.trim()) return;
    onConfirm(path.trim());
  }

  return (
    <div className="palette-overlay" onClick={onCancel}>
      <div className="rename-modal" onClick={(e) => e.stopPropagation()}>
        <div className="rename-modal-title">Save to workspace</div>
        <form onSubmit={submit}>
          <label>File path</label>
          <input type="text" value={path} autoFocus onChange={(e) => setPath(e.target.value)} />
          <div className="rename-modal-actions">
            <button type="button" className="btn" onClick={onCancel}>Cancel</button>
            <button type="submit" className="btn primary" disabled={!path.trim()}>Save</button>
          </div>
        </form>
      </div>
    </div>
  );
}

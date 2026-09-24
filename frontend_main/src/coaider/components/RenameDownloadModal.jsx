import React, { useEffect, useState } from 'react';

export default function RenameDownloadModal({ path, onCancel, onConfirm }) {
  const [name, setName] = useState('');

  useEffect(() => {
    if (path) setName(path.split('/').pop());
  }, [path]);

  if (!path) return null;

  function submit(e) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    onConfirm(path, trimmed);
  }

  return (
    <div className="palette-overlay" onClick={onCancel}>
      <div className="rename-modal" onClick={(e) => e.stopPropagation()}>
        <div className="rename-modal-title">Download file</div>
        <div className="rename-modal-sub mono dim small">{path}</div>
        <form onSubmit={submit}>
          <label>Save as</label>
          <input
            type="text"
            value={name}
            autoFocus
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === 'Escape' && onCancel()}
          />
          <div className="rename-modal-actions">
            <button type="button" className="btn" onClick={onCancel}>Cancel</button>
            <button type="submit" className="btn primary" disabled={!name.trim()}>Download</button>
          </div>
        </form>
      </div>
    </div>
  );
}

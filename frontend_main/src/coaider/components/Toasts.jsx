import React from 'react';

const ICON = { success: '✓', error: '✕', info: 'ℹ' };

export default function Toasts({ toasts }) {
  return (
    <div className="toast-stack">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast-${t.kind || 'info'}`}>
          <span className="toast-icon">{ICON[t.kind] || ICON.info}</span>
          <span>{t.message}</span>
        </div>
      ))}
    </div>
  );
}

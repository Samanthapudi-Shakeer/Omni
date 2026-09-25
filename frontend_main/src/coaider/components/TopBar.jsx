import React from 'react';

export default function TopBar({ model, mode, busy }) {
  return (
    <header className="topbar">
      <div className="topbar-title">{model || '—'}</div>
      <div className="topbar-mode">{(mode || '').toUpperCase()}</div>
      <div className="topbar-spacer" />
      <div className={`busy-indicator${busy ? ' busy' : ''}`}>
        <span className="dot" /> {busy ? 'working…' : 'idle'}
      </div>
    </header>
  );
}

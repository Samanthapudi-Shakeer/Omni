import React, { useState } from 'react';

export default function WorkspaceBar({ workspaces, current, onSelect, onCreate }) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [error, setError] = useState('');

  async function submit(e) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    try {
      setError('');
      await onCreate(trimmed);
      setName('');
      setCreating(false);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="workspace-bar">
      <label>Workspace</label>
      <div className="workspace-row">
        <select
          value={current || ''}
          onChange={(e) => onSelect(e.target.value)}
          disabled={workspaces.length === 0}
        >
          {workspaces.length === 0 && <option value="">No workspaces yet</option>}
          {workspaces.map((w) => (
            <option key={w.name} value={w.name}>{w.name}</option>
          ))}
        </select>
        <button type="button" className="btn small" onClick={() => setCreating((v) => !v)}>
          {creating ? 'Cancel' : '+ New'}
        </button>
      </div>
      {creating && (
        <form className="workspace-create" onSubmit={submit}>
          <input
            type="text"
            placeholder="workspace-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />
          <button type="submit" className="btn small primary">Create</button>
        </form>
      )}
      {error && <div className="field-error">{error}</div>}
    </div>
  );
}

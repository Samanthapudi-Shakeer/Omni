import { useState } from 'react'

export default function WorkspacePicker({ workspaces, onSelect, onCreate }) {
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const create = async event => {
    event.preventDefault()
    if (!name.trim()) return
    setBusy(true); setError('')
    try { await onCreate(name.trim()) }
    catch (err) { setError(err?.response?.data?.detail || err.message || 'Could not create workspace.') }
    finally { setBusy(false) }
  }

  return <div className="workspace-picker-backdrop" role="dialog" aria-modal="true" aria-label="Choose a workspace">
    <section className="workspace-picker">
      <div className="brand"><div className="brand-dot" /><div className="brand-title">OmniZen AI</div></div>
      <h1>Choose a workspace</h1>
      <p>Select an existing workspace or create one before using any feature. Coaider and every feature tab use this same workspace.</p>
      {workspaces.length > 0 && <div className="workspace-picker-list">
        {workspaces.map(item => <button key={item.name} className="btn" onClick={() => onSelect(item.name)}>{item.name}</button>)}
      </div>}
      <form onSubmit={create} className="workspace-add-form">
        <input className="input" value={name} onChange={event => setName(event.target.value)} placeholder="new-workspace-name" disabled={busy} />
        <button className="btn primary" disabled={busy || !name.trim()}>{busy ? 'Creating…' : 'Create workspace'}</button>
      </form>
      {error && <div className="error">{error}</div>}
    </section>
  </div>
}

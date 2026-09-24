import { useState } from 'react'
import { createWorkspaceFile, deleteWorkspaceFile, extractErrorMessage } from '../api/client'

export default function WorkspaceManager({ workspace, files, refreshFiles }) {
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const addFile = async (event) => {
    event.preventDefault()
    if (!name.trim()) return
    setBusy(true); setError('')
    try {
      await createWorkspaceFile(workspace, name.trim())
      setName('')
      refreshFiles()
    } catch (e) { setError(extractErrorMessage(e)) }
    finally { setBusy(false) }
  }

  const removeFile = async (file) => {
    if (!window.confirm(`Delete ${file.name}? This cannot be undone.`)) return
    setBusy(true); setError('')
    try { await deleteWorkspaceFile(workspace, file.name); refreshFiles() }
    catch (e) { setError(extractErrorMessage(e)) }
    finally { setBusy(false) }
  }

  return (
    <div className="panel workspace-manager">
      <h3>Manage Workspace</h3>
      <div className="hint">Add a blank file or remove files from the active workspace.</div>
      <form className="workspace-add-form" onSubmit={addFile}>
        <input className="input" value={name} onChange={e => setName(e.target.value)}
          placeholder="path/to/new-file.py" disabled={busy} />
        <button className="btn primary" disabled={busy || !name.trim()}>Add file</button>
      </form>
      {error && <div className="error">{error}</div>}
      <div className="workspace-file-actions">
        {files.map(file => (
          <div key={file.name} className="workspace-file-action">
            <span title={file.name}>{file.name}</span>
            <button className="btn small danger-text" onClick={() => removeFile(file)} disabled={busy}>Delete</button>
          </div>
        ))}
        {!files.length && <span className="empty-state">No files in this workspace.</span>}
      </div>
    </div>
  )
}

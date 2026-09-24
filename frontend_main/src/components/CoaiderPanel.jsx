import { useState } from 'react'
import { startCoaiderSession, extractErrorMessage } from '../api/client'
import TerminalView from './TerminalView'

const DEFAULT_PROMPT = 'Review the attached files and help me implement the requested change. Explain your plan, then make the changes after confirmation when needed.'

export default function CoaiderPanel({ workspace, attached, onFilesChanged }) {
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT)
  const [sessionId, setSessionId] = useState(null)
  const [error, setError] = useState('')
  const [changedFiles, setChangedFiles] = useState([])
  const [starting, setStarting] = useState(false)

  const startSession = async () => {
    setStarting(true)
    setError('')
    setChangedFiles([])
    try {
      const result = await startCoaiderSession(workspace, attached.map(file => file.name), prompt)
      setSessionId(result.session_id)
    } catch (err) {
      setError(extractErrorMessage(err))
    } finally {
      setStarting(false)
    }
  }

  return (
    <div className="panel coaider-panel">
      <h3>Coaider</h3>
      <p className="hint">Work with Aider interactively in the active <strong>{workspace}</strong> workspace. Attach files from the sidebar, then start a session.</p>
      <div className="coaider-attached">
        <strong>Attached files</strong>
        {attached.length ? <span>{attached.map(file => file.name).join(', ')}</span> : <span className="empty-state">No files attached — select files in the sidebar first.</span>}
      </div>
      <label className="field-label" htmlFor="coaider-prompt">Task for Coaider</label>
      <textarea id="coaider-prompt" className="input" value={prompt} onChange={event => setPrompt(event.target.value)} disabled={starting || Boolean(sessionId)} />
      <div className="coaider-actions">
        <button className="btn primary" onClick={startSession} disabled={starting || Boolean(sessionId) || !attached.length || !prompt.trim()}>
          {starting ? 'Starting…' : 'Start Coaider session'}
        </button>
        {sessionId && <button className="btn" onClick={() => setSessionId(null)}>New session</button>}
      </div>
      {error && <div className="error">{error}</div>}
      {sessionId && <TerminalView sessionId={sessionId} onError={setError} onExit={files => { setChangedFiles(files); onFilesChanged() }} />}
      {changedFiles.length > 0 && <div className="coaider-result">Saved to <strong>{workspace}</strong>: {changedFiles.join(', ')}</div>}
    </div>
  )
}

import { useEffect, useRef, useState } from 'react'
import { getDefaultModularizePrompt, startModularizeSession, extractErrorMessage } from '../api/client'
import TerminalView from './TerminalView'
import SessionStatusPill from './SessionStatusPill'

export default function ModularizationPanel({ workspace, attached, onFilesChanged }) {
  const [selectedFile, setSelectedFile] = useState('')
  const [prompt, setPrompt] = useState('')
  const [sessionId, setSessionId] = useState(null)
  const [starting, setStarting] = useState(false)
  const [terminalEnded, setTerminalEnded] = useState(false)
  const [changedFiles, setChangedFiles] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    getDefaultModularizePrompt().then(setPrompt).catch(() => {})
  }, [])

  // Panel stays mounted app-wide (tabs are CSS-hidden, not unmounted - see
  // App.jsx), so a tab switch alone never touches this. Only reset on an
  // actual workspace change - a stale session/result from a different
  // workspace would be misleading here.
  const isFirstRun = useRef(true)
  useEffect(() => {
    if (isFirstRun.current) { isFirstRun.current = false; return }
    setSessionId(null)
    setTerminalEnded(false)
    setChangedFiles(null)
    setError(null)
  }, [workspace])

  useEffect(() => {
    if (!selectedFile && attached.length > 0) setSelectedFile(attached[0].name)
    if (selectedFile && !attached.find(f => f.name === selectedFile)) {
      setSelectedFile(attached[0]?.name || '')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attached])

  const status = error ? 'error'
    : starting ? 'starting'
    : sessionId && !terminalEnded ? 'running'
    : changedFiles ? 'done'
    : 'idle'

  const handleStart = async () => {
    if (!selectedFile || !prompt.trim()) return
    setStarting(true)
    setError(null)
    setChangedFiles(null)
    setTerminalEnded(false)
    try {
      const res = await startModularizeSession(workspace, selectedFile, prompt)
      setSessionId(res.session_id)
    } catch (e) {
      setError(extractErrorMessage(e))
    } finally {
      setStarting(false)
    }
  }

  const handleExit = (files) => {
    setTerminalEnded(true)
    setChangedFiles(files)
    if (files?.length) onFilesChanged?.()
  }

  const handleNewSession = () => {
    setSessionId(null)
    setTerminalEnded(false)
    setChangedFiles(null)
    setError(null)
  }

  return (
    <div className="session-layout">
      <div className="session-controls">
        <div className="panel">
          <div className="panel-header-row">
            <h3>Modularization</h3>
            <SessionStatusPill status={status} />
          </div>
          <div className="hint">
            Pick an attached file, edit the prompt if you want a specific split, then start an
            isolated, genuinely <strong>interactive</strong> aider session - just like Test Case
            Generation. Aider may ask Y/N questions (e.g. "Create modules/foo.py?") and you answer
            them directly in the terminal, exactly as if you were running aider yourself. A few
            known low-value prompts (like the LLM-warnings documentation link) are answered "No"
            automatically so the session never stalls waiting on something unrelated to your task.
            The terminal keeps streaming even if you switch to another tab and come back.
          </div>

          <div className="section-label">FILE TO MODULARIZE</div>
          <select
            className="select" style={{ width: '100%', marginBottom: 12 }}
            value={selectedFile} onChange={e => setSelectedFile(e.target.value)}
            disabled={!!sessionId}
          >
            <option value="">Select an attached file…</option>
            {attached.map(f => <option key={f.name} value={f.name}>{f.name}</option>)}
          </select>

          <div className="section-label">PROMPT (editable before sending)</div>
          <textarea
            className="input"
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
            disabled={!!sessionId}
          />

          <div style={{ marginTop: 12 }}>
            {!sessionId ? (
              <button
                className="btn primary"
                onClick={handleStart}
                disabled={starting || !selectedFile || !prompt.trim()}
              >
                {starting ? <><span className="spinner" /> Starting session…</> : 'Start Modularization Session'}
              </button>
            ) : (
              <button className="btn small ghost" onClick={handleNewSession}>
                New Session
              </button>
            )}
          </div>
          {error && <div className="hint" style={{ color: 'var(--err)', marginTop: 8 }}>{error}</div>}
        </div>
      </div>

      <div className="session-main">
        {sessionId && (
          <div className="panel">
            <div className="panel-header-row">
              <h3>Session Terminal</h3>
              <SessionStatusPill status={status} />
            </div>
            <div className="hint">
              Type your reply (e.g. <code>Y</code>, <code>N</code>, or free text) and press Enter —
              this is a live terminal, not a chat box.
            </div>
            <div className="terminal-window">
              <div className="terminal-chrome">
                <div className="terminal-dots"><span /><span /><span /></div>
                <span className="terminal-chrome-label">aider — modularize: {selectedFile}</span>
              </div>
              <TerminalView
                sessionId={sessionId}
                onExit={handleExit}
                onError={setError}
              />
            </div>
          </div>
        )}

        {changedFiles && (
          <div className="panel">
            <h3>Result</h3>
            {changedFiles.length === 0 ? (
              <div className="hint">Session ended — no new or changed files were produced.</div>
            ) : (
              <>
                <div className="section-label">NEW / CHANGED FILES</div>
                <div className="chip-list">
                  {changedFiles.map(f => <span className="file-chip changed" key={f}>{f}</span>)}
                </div>
                <div className="hint">Copied back into the workspace — refresh the file list in the sidebar to see them.</div>
              </>
            )}
          </div>
        )}

        {!sessionId && !changedFiles && (
          <div className="panel"><div className="empty-state">No session started yet.</div></div>
        )}
      </div>
    </div>
  )
}

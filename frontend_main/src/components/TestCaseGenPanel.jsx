import { useEffect, useState } from 'react'
import { getDefaultTestGenPrompt, startTestGenSession, extractErrorMessage } from '../api/client'
import TerminalView from './TerminalView'
import SessionStatusPill from './SessionStatusPill'

export default function TestCaseGenPanel({ workspace, attached, onFilesChanged }) {
  const [prompt, setPrompt] = useState('')
  const [sessionId, setSessionId] = useState(null)
  const [starting, setStarting] = useState(false)
  const [terminalEnded, setTerminalEnded] = useState(false)
  const [changedFiles, setChangedFiles] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    getDefaultTestGenPrompt().then(setPrompt).catch(() => {})
  }, [])

  const status = error ? 'error'
    : starting ? 'starting'
    : sessionId && !terminalEnded ? 'running'
    : changedFiles ? 'done'
    : 'idle'

  const handleStart = async () => {
    if (attached.length === 0 || !prompt.trim()) return
    setStarting(true)
    setError(null)
    setChangedFiles(null)
    setTerminalEnded(false)
    try {
      const res = await startTestGenSession(workspace, attached.map(f => f.name), prompt)
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
            <h3>Test Case Generation</h3>
            <SessionStatusPill status={status} />
          </div>
          <div className="hint">
            Attach file(s) in the sidebar, edit the prompt if you like, then start an isolated
            aider session. This is a real interactive session — aider may ask Y/N questions (e.g.
            "Add tests/test_foo.py to the chat?") and you answer them directly in the terminal, just
            like running aider yourself. A few known low-value prompts (like the LLM-warnings
            documentation link) are answered "No" automatically so the session never stalls
            waiting on something unrelated to your task. The terminal keeps streaming even if you
            switch to another tab and come back.
          </div>

          <div className="section-label">ATTACHED FILES</div>
          {attached.length === 0 ? (
            <div className="hint">Attach files in the sidebar first.</div>
          ) : (
            <div className="chip-list">
              {attached.map(f => <span className="file-chip" key={f.name}>{f.name}</span>)}
            </div>
          )}

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
                disabled={starting || attached.length === 0 || !prompt.trim()}
              >
                {starting ? <><span className="spinner" /> Starting session…</> : 'Start Test Generation Session'}
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
                <span className="terminal-chrome-label">
                  aider — test-gen: {attached.map(f => f.name).join(', ')}
                </span>
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
                <div className="section-label">FILE(S) CREATED / CHANGED</div>
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

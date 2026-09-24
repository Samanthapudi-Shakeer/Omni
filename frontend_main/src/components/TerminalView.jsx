import { useEffect, useRef } from 'react'
import { Terminal } from 'xterm'
import { FitAddon } from 'xterm-addon-fit'
import 'xterm/css/xterm.css'

export default function TerminalView({ sessionId, endpoint = '/api/pty/ws', onExit, onError }) {
  const containerRef = useRef(null)

  useEffect(() => {
    let disposed = false      // true once cleanup has run - guards against
                               // writing to an already-disposed terminal
                               // from an async WS event that fires after
                               // unmount/session-change (a real race: ws.close()
                               // is async, term.dispose() runs right after it
                               // in cleanup, so a late close/message event
                               // could otherwise hit a dead terminal instance).
    let sessionEnded = false  // true once we've handled a clean 'exit' message
    let issueReported = false // true once onerror already wrote a message,
                               // so the close handler that (per spec) follows
                               // it doesn't print a confusing duplicate

    const term = new Terminal({
      convertEol: true,
      fontSize: 13,
      fontFamily: "'JetBrains Mono', monospace",
      theme: {
        background: '#14151f',
        foreground: '#d7d8e5',
        cursor: '#6C5CE7',
      },
      cursorBlink: true,
      scrollback: 2000,
    })
    const fitAddon = new FitAddon()
    term.loadAddon(fitAddon)
    term.open(containerRef.current)
    fitAddon.fit()
    term.writeln('Connecting to isolated aider session…\r\n')

    const safeWrite = (text) => {
      if (disposed) return
      try { term.write(text) } catch { /* terminal already torn down - ignore */ }
    }

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${window.location.host}${endpoint}/${sessionId}`)

    const safeSend = (payload) => {
      if (ws.readyState !== WebSocket.OPEN) return
      try {
        ws.send(JSON.stringify(payload))
      } catch (e) {
        // Sending can throw synchronously in rare state-transition edge
        // cases - never let that escape as an uncaught error.
        console.warn('[TerminalView] failed to send over WebSocket:', e)
      }
    }

    ws.onopen = () => {
      safeSend({ type: 'resize', rows: term.rows, cols: term.cols })
    }

    ws.onmessage = (event) => {
      if (disposed) return
      let msg
      try {
        msg = JSON.parse(event.data)
      } catch {
        return // malformed frame - ignore rather than throw
      }
      if (msg.type === 'output') {
        safeWrite(msg.data)
      } else if (msg.type === 'exit') {
        sessionEnded = true
        safeWrite('\r\n\x1b[33m[session ended]\x1b[0m\r\n')
        onExit?.(msg.changed_files || [])
      } else if (msg.type === 'error') {
        issueReported = true
        safeWrite(`\r\n\x1b[31m${msg.data}\x1b[0m\r\n`)
        onError?.(msg.data)
      }
    }

    ws.onerror = () => {
      // The browser's WebSocket error event carries no useful detail by
      // spec, and is always immediately followed by a close event - so
      // just flag it here and let onclose do the (single) user-facing
      // reporting, avoiding a duplicated message.
      issueReported = true
      console.warn(`[TerminalView] WebSocket error for session ${sessionId}`)
    }

    ws.onclose = (event) => {
      if (disposed || sessionEnded) return
      // A close that isn't our own clean 'exit' message means the
      // connection dropped unexpectedly (network blip, backend restart,
      // proxy hiccup, etc.) - report it clearly instead of leaving the
      // terminal looking silently frozen with no explanation.
      if (!issueReported) {
        const reasonSuffix = event.reason ? `: ${event.reason}` : ''
        safeWrite(`\r\n\x1b[31m[connection lost${reasonSuffix}]\x1b[0m\r\n`)
      } else {
        safeWrite('\r\n\x1b[31m[connection lost]\x1b[0m\r\n')
      }
      onError?.('Connection to the session was lost. The session may still be running on the server.')
    }

    const dataDisposable = term.onData((data) => {
      safeSend({ type: 'input', data })
    })

    const resizeDisposable = term.onResize(({ rows, cols }) => {
      safeSend({ type: 'resize', rows, cols })
    })

    // Genuine "dynamic resolution" support: whenever the window (and so
    // the container's viewport-relative height/width) changes, re-measure
    // and tell the PTY the new size, rather than leaving the terminal
    // fixed at whatever size it happened to open at.
    const handleWindowResize = () => {
      if (disposed) return
      try { fitAddon.fit() } catch { /* container may be mid-teardown */ }
    }
    window.addEventListener('resize', handleWindowResize)

    return () => {
      disposed = true
      window.removeEventListener('resize', handleWindowResize)
      dataDisposable.dispose()
      resizeDisposable.dispose()
      // Detach handlers before closing so a close event fired as a direct
      // result of our own ws.close() call below never reaches the
      // (already-disposed) terminal.
      ws.onopen = null
      ws.onmessage = null
      ws.onerror = null
      ws.onclose = null
      ws.close()
      term.dispose()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])

  return <div ref={containerRef} className="terminal-view" />
}

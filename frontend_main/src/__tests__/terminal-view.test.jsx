import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import TerminalView from '../components/TerminalView'

// A controllable fake WebSocket standing in for the real thing - lets the
// test fire open/message/error/close events on demand and inspect what the
// component sent, without needing a real server.
class FakeWebSocket {
  static OPEN = 1
  static CLOSED = 3
  static instances = []

  constructor(url) {
    this.url = url
    this.readyState = FakeWebSocket.OPEN
    this.sent = []
    this.onopen = null
    this.onmessage = null
    this.onerror = null
    this.onclose = null
    FakeWebSocket.instances.push(this)
  }

  send(data) {
    if (this.readyState !== FakeWebSocket.OPEN) {
      throw new Error('WebSocket is not open')
    }
    this.sent.push(data)
  }

  close() {
    this.readyState = FakeWebSocket.CLOSED
    // Real browsers dispatch close asynchronously - mirror that so we can
    // test the "message arrives after the component already tore down"
    // race the component's `disposed` guard exists for.
    setTimeout(() => this.onclose?.({ code: 1000, reason: '', wasClean: true }), 0)
  }

  // Test helpers - not part of the real WebSocket API.
  emitOpen() { this.onopen?.() }
  emitMessage(payload) { this.onmessage?.({ data: JSON.stringify(payload) }) }
  emitError() { this.onerror?.(new Event('error')) }
  emitClose(opts = {}) { this.onclose?.({ code: 1006, reason: '', wasClean: false, ...opts }) }
}

let uncaughtErrors
let unhandledRejections

function trackGlobalErrors() {
  uncaughtErrors = []
  unhandledRejections = []
  const onError = (e) => uncaughtErrors.push(e.error || e.message)
  const onRejection = (e) => unhandledRejections.push(e.reason)
  window.addEventListener('error', onError)
  window.addEventListener('unhandledrejection', onRejection)
  return () => {
    window.removeEventListener('error', onError)
    window.removeEventListener('unhandledrejection', onRejection)
  }
}

describe('TerminalView WebSocket lifecycle hardening', () => {
  let originalWebSocket
  let untrack

  beforeEach(() => {
    originalWebSocket = global.WebSocket
    global.WebSocket = FakeWebSocket
    FakeWebSocket.instances = []
    untrack = trackGlobalErrors()
  })

  afterEach(() => {
    global.WebSocket = originalWebSocket
    untrack()
    cleanup()
  })

  it('reports an unexpected close (no prior exit message) via onError, with no uncaught errors', async () => {
    const onExit = vi.fn()
    const onError = vi.fn()
    render(<TerminalView sessionId="s1" onExit={onExit} onError={onError} />)

    const ws = FakeWebSocket.instances[0]
    ws.emitOpen()
    ws.emitMessage({ type: 'output', data: 'hello\r\n' })

    // Connection drops WITHOUT us ever having sent/received an 'exit'
    // message - e.g. a network blip or backend restart.
    ws.emitClose()

    expect(onError).toHaveBeenCalledWith(expect.stringContaining('Connection to the session was lost'))
    expect(onExit).not.toHaveBeenCalled()
    expect(uncaughtErrors).toEqual([])
    expect(unhandledRejections).toEqual([])
  })

  it('does not report a fake "connection lost" after a clean exit message', async () => {
    const onExit = vi.fn()
    const onError = vi.fn()
    render(<TerminalView sessionId="s2" onExit={onExit} onError={onError} />)

    const ws = FakeWebSocket.instances[0]
    ws.emitOpen()
    ws.emitMessage({ type: 'exit', changed_files: ['test_foo.py'] })
    ws.emitClose() // the server's own close, following its own exit message

    expect(onExit).toHaveBeenCalledWith(['test_foo.py'])
    expect(onError).not.toHaveBeenCalled()
    expect(uncaughtErrors).toEqual([])
  })

  it('never throws when a message arrives after the component has already unmounted', async () => {
    const onExit = vi.fn()
    const onError = vi.fn()
    const { unmount } = render(<TerminalView sessionId="s3" onExit={onExit} onError={onError} />)

    const ws = FakeWebSocket.instances[0]
    ws.emitOpen()

    // Unmount right away (e.g. the user clicked "New Session" or navigated
    // off this session) - this is the real race the `disposed` flag and
    // detached handlers in TerminalView exist to guard against: the fake
    // ws.close() called during cleanup schedules an async close event.
    unmount()

    // A message that arrives after teardown must be silently ignored, not
    // throw - simulate the server still having something queued.
    expect(() => ws.emitMessage({ type: 'output', data: 'late data\r\n' })).not.toThrow()

    // Let the scheduled async close (from ws.close() during our own
    // cleanup) actually fire, and confirm it doesn't throw or get reported
    // as a "connection lost" after the component is already gone.
    await new Promise((r) => setTimeout(r, 10))

    expect(uncaughtErrors).toEqual([])
    expect(unhandledRejections).toEqual([])
    // onError must not fire for our own intentional teardown-triggered close.
    expect(onError).not.toHaveBeenCalled()
  })

  it('guards send() so it never throws even if called while the socket is closed', async () => {
    render(<TerminalView sessionId="s4" onExit={vi.fn()} onError={vi.fn()} />)
    const ws = FakeWebSocket.instances[0]
    ws.readyState = FakeWebSocket.CLOSED // simulate socket already closed

    // onopen would normally send the initial resize - with the socket
    // already closed, safeSend's readyState guard must skip it rather
    // than calling ws.send() (which would throw per our fake's contract).
    expect(() => ws.emitOpen()).not.toThrow()
    expect(ws.sent).toEqual([])
    expect(uncaughtErrors).toEqual([])
  })
})

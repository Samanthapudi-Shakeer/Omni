import { Component } from 'react'

// Without this, an uncaught error anywhere in a panel's render tree (e.g. a
// malformed API response reaching JSX in an unexpected shape) unmounts
// EVERYTHING above it that isn't itself an error boundary - in this app
// that used to mean the whole <App/>, wiping every tab's in-progress work
// at once. Wrapping each tab's panel in its own boundary confines that
// blast radius to just the panel that crashed; the other tabs, the
// sidebar, and the jobs tray are unaffected and keep their state.
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error(`[${this.props.label || 'panel'}] crashed:`, error, info)
  }

  handleReset = () => {
    this.setState({ error: null })
  }

  render() {
    if (this.state.error) {
      return (
        <div className="panel">
          <h3>Something went wrong in {this.props.label || 'this panel'}</h3>
          <div className="hint" style={{ color: 'var(--err)' }}>
            {this.state.error?.message || String(this.state.error)}
          </div>
          <div className="hint">
            Your data in the other tabs is unaffected - only this panel needs to reload.
          </div>
          <button className="btn small" onClick={this.handleReset} style={{ marginTop: 8 }}>
            Reload this panel
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

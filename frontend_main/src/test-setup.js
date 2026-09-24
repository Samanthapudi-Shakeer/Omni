import '@testing-library/jest-dom/vitest'

// jsdom does not implement matchMedia (it doesn't evaluate real CSS media
// queries) - xterm.js's screen-DPR monitor calls it unconditionally on
// Terminal.open(), so without this polyfill any test that actually mounts
// a <TerminalView> fails with "matchMedia is not a function" before it
// even reaches the code under test.
if (typeof window !== 'undefined' && !window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })
}

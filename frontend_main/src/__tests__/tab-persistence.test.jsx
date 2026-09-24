import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import App from '../App'

// Mock every API call the app makes on mount so this test is purely about
// tab-switch/mount behavior, not real network/backend behavior.
vi.mock('../api/client', () => ({
  listFiles: vi.fn().mockResolvedValue([]),
  uploadFile: vi.fn(),
  runAnalysis: vi.fn(),
  askAI: vi.fn(),
  getReportUrl: vi.fn(() => '#'),
  getDefaultModularizePrompt: vi.fn().mockResolvedValue('DEFAULT MODULARIZE PROMPT'),
  getFileHistory: vi.fn(),
  getFileDiff: vi.fn(),
  getDefaultTestGenPrompt: vi.fn().mockResolvedValue('DEFAULT TESTGEN PROMPT'),
  startTestGenSession: vi.fn(),
  startCoaiderSession: vi.fn(),
  getTranslateLanguages: vi.fn().mockResolvedValue({
    source_languages: [{ code: 'auto', name: 'Auto Detect' }, { code: 'en', name: 'English' }],
    target_languages: [{ code: 'en', name: 'English' }, { code: 'es', name: 'Spanish' }],
  }),
  getTranslateModels: vi.fn().mockResolvedValue({ models: [{ name: 'qwen2.5-coder:32b' }], default_model: 'qwen2.5-coder:32b' }),
  getVisionModels: vi.fn().mockResolvedValue({ models: [] }),
  translateImage: vi.fn(),
  translateText: vi.fn(),
  startFixAllJob: vi.fn(),
  startModularizeSession: vi.fn(),
  startTranslateOfficeDocJob: vi.fn(),
  getJob: vi.fn(),
  default: {},
}))

describe('tab switching preserves in-progress state', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('keeps every tab panel mounted in the DOM at all times (CSS-hidden, not removed)', async () => {
    render(<App />)

    const analysisPanel = await screen.findByTestId('tab-panel-analysis')
    const modularizePanel = screen.getByTestId('tab-panel-modularize')
    const coaiderPanel = screen.getByTestId('tab-panel-coaider')
    const testgenPanel = screen.getByTestId('tab-panel-testgen')
    const translatePanel = screen.getByTestId('tab-panel-translate')
    const diffkitPanel = screen.getByTestId('tab-panel-diffkit')

    // All five exist from the start, analysis visible, rest hidden.
    expect(analysisPanel).toBeInTheDocument()
    expect(getComputedStyle(analysisPanel).display).not.toBe('none')
    expect(getComputedStyle(modularizePanel).display).toBe('none')
    expect(getComputedStyle(coaiderPanel).display).toBe('none')
    expect(getComputedStyle(testgenPanel).display).toBe('none')
    expect(getComputedStyle(translatePanel).display).toBe('none')
    expect(getComputedStyle(diffkitPanel).display).toBe('none')

    // Switch to Modularization.
    fireEvent.click(screen.getByRole('button', { name: 'Modularization' }))

    // The critical assertion: the analysis panel must STILL be in the
    // document (same DOM subtree, same component instance) rather than
    // torn down - this is what actually preserves its internal state.
    expect(analysisPanel).toBeInTheDocument()
    expect(document.body.contains(analysisPanel)).toBe(true)
    expect(getComputedStyle(analysisPanel).display).toBe('none')
    expect(getComputedStyle(modularizePanel).display).not.toBe('none')

    fireEvent.click(screen.getByRole('button', { name: 'Coaider' }))
    expect(document.body.contains(modularizePanel)).toBe(true)
    expect(getComputedStyle(coaiderPanel).display).not.toBe('none')

    // Switch to Test Case Generation, then Translate, then Diff Kit, then
    // back to Analysis.
    fireEvent.click(screen.getByRole('button', { name: 'Test Case Generation' }))
    expect(document.body.contains(modularizePanel)).toBe(true)
    expect(document.body.contains(analysisPanel)).toBe(true)

    fireEvent.click(screen.getByRole('button', { name: 'Requirement Understanding' }))
    expect(document.body.contains(testgenPanel)).toBe(true)

    fireEvent.click(screen.getByRole('button', { name: 'Diff Kit' }))
    expect(document.body.contains(translatePanel)).toBe(true)
    expect(getComputedStyle(diffkitPanel).display).not.toBe('none')
    // Diff Kit's iframe (its own self-contained document) must persist
    // across tab switches too - re-rendering it would reset any files the
    // user already dropped in.
    expect(diffkitPanel.querySelector('iframe[title="Diff Kit"]')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Static Code Analysis' }))
    expect(getComputedStyle(analysisPanel).display).not.toBe('none')
    expect(getComputedStyle(translatePanel).display).toBe('none')
    expect(getComputedStyle(diffkitPanel).display).toBe('none')
    // The translate panel node is still the exact same node as before -
    // never unmounted/remounted.
    expect(screen.getByTestId('tab-panel-translate')).toBe(translatePanel)
    // Same for the Diff Kit panel and its iframe.
    expect(screen.getByTestId('tab-panel-diffkit')).toBe(diffkitPanel)
  })

  it('a value typed into Modularization survives switching tabs away and back', async () => {
    render(<App />)

    fireEvent.click(screen.getByRole('button', { name: 'Modularization' }))

    // Wait for the default prompt to load, then overwrite it with a
    // distinctive value the test controls.
    const textarea = await screen.findByDisplayValue('DEFAULT MODULARIZE PROMPT')
    fireEvent.change(textarea, { target: { value: 'MY CUSTOM UNSAVED PROMPT TEXT' } })
    expect(textarea.value).toBe('MY CUSTOM UNSAVED PROMPT TEXT')

    // Switch away to another tab and back.
    fireEvent.click(screen.getByRole('button', { name: 'Static Code Analysis' }))
    fireEvent.click(screen.getByRole('button', { name: 'Test Case Generation' }))
    fireEvent.click(screen.getByRole('button', { name: 'Modularization' }))

    // If the panel had been unmounted (the old bug), this textarea would
    // have reset back to the fetched default prompt. It must not have.
    const textareaAgain = screen.getByDisplayValue('MY CUSTOM UNSAVED PROMPT TEXT')
    expect(textareaAgain).toBeInTheDocument()
  })
})

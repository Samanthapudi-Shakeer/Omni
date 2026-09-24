import React, { useEffect, useRef } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { WebLinksAddon } from '@xterm/addon-web-links';
import '@xterm/xterm/css/xterm.css';

/**
 * Wraps xterm.js -- a real terminal emulator -- so Aider's actual output
 * (ANSI colors, cursor repositioning, spinners, interactive prompts) renders
 * exactly as it would in a real terminal. `write` is called with base64
 * chunks decoded straight from the PTY; nothing is reinterpreted or
 * reformatted here.
 */
export default function TerminalView({ onWriteRef, onResize, initialChunks }) {
  const containerRef = useRef(null);
  const termRef = useRef(null);
  const fitRef = useRef(null);

  useEffect(() => {
    const term = new Terminal({
      convertEol: false,
      fontFamily: "'JetBrains Mono', ui-monospace, monospace",
      fontSize: 13,
      scrollback: 10000,
      allowProposedApi: true,
      theme: {
        background: '#1b1f27',
        foreground: '#e7ebef',
        cursor: '#818cf8',
        selectionBackground: '#4f46e544',
        black: '#1b1f27',
        brightBlack: '#5b6472',
        red: '#f5776f',
        green: '#6fcf97',
        yellow: '#e0a542',
        blue: '#7aa2f7',
        magenta: '#c792ea',
        cyan: '#5bc8d9',
        white: '#e7ebef',
      },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.loadAddon(new WebLinksAddon());
    term.open(containerRef.current);
    fit.fit();

    termRef.current = term;
    fitRef.current = fit;

    // Replay anything that arrived while this view wasn't mounted (e.g. the
    // user was in Supervised Mode), so switching back doesn't lose context.
    if (initialChunks && initialChunks.length) {
      for (const chunk of initialChunks) term.write(chunk);
    }

    if (onWriteRef) {
      onWriteRef.current = (bytes) => term.write(bytes);
    }

    const resizeObserver = new ResizeObserver(() => {
      try {
        fit.fit();
        onResize?.(term.cols, term.rows);
      } catch (_) {
        /* ignore transient resize errors */
      }
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      term.dispose();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <div className="terminal-view" ref={containerRef} />;
}

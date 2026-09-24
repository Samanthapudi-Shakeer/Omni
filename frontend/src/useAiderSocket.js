import { useEffect, useRef } from 'react';
import { getToken } from './api';

/**
 * Connects to /ws/{workspaceName} and dispatches incoming messages to the
 * provided handlers. Auto-reconnects with a fixed backoff, and reconnects
 * fresh whenever `workspaceName` changes (switching workspaces means a
 * different, independent Aider session/output stream).
 */
export function useAiderSocket(workspaceName, handlers) {
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  useEffect(() => {
    if (!workspaceName) return undefined;

    let ws;
    let retryTimer;
    let closedByUs = false;

    function connect() {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      const token = getToken();
      const qs = token ? `?token=${encodeURIComponent(token)}` : '';
      ws = new WebSocket(`${proto}://${location.host}/ws/${encodeURIComponent(workspaceName)}${qs}`);

      ws.onopen = () => handlersRef.current.onOpen?.();
      ws.onclose = () => {
        handlersRef.current.onClose?.();
        if (!closedByUs) retryTimer = setTimeout(connect, 2000);
      };
      ws.onerror = () => {
        /* onclose follows and triggers the retry */
      };
      ws.onmessage = (evt) => {
        let msg;
        try {
          msg = JSON.parse(evt.data);
        } catch (_) {
          return;
        }
        handlersRef.current.onMessage?.(msg);
      };
    }

    connect();
    return () => {
      closedByUs = true;
      clearTimeout(retryTimer);
      ws?.close();
    };
  }, [workspaceName]);
}

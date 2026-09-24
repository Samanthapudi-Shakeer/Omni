import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    // Override with VITE_API_TARGET when the backend is hosted elsewhere.
    host: true,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://localhost:8080',
        ws: true,
        // Vite's dev proxy (built on Node's `http-proxy`) does not attach an
        // 'error' listener to the sockets it opens to the backend by
        // default in all versions/code paths. If the backend restarts
        // (e.g. `uvicorn --reload` picking up a file change) or a
        // connection is abruptly reset while a request or WebSocket is in
        // flight - very possible here given this app's long-lived PTY
        // terminal sessions (Modularization, Test Case Generation) and
        // frequent job-status polling - that can surface as an uncaught
        // "Unhandled 'error' event... ECONNRESET" and crash the Vite dev
        // server process, which then drops its own HMR WebSocket to the
        // browser and can show up as the page reloading/resetting mid-task.
        // Attaching handlers here converts that into a logged warning.
        configure: (proxy) => {
          proxy.on('error', (err, _req, res) => {
            console.warn('[vite proxy] error:', err.code || err.message)
            if (res && typeof res.writeHead === 'function' && !res.headersSent) {
              res.writeHead(502, { 'Content-Type': 'text/plain' })
              res.end('Bad gateway - backend unavailable or restarting.')
            }
          })
          proxy.on('proxyReqWs', (_proxyReq, _req, socket) => {
            socket.on('error', (err) => {
              console.warn('[vite proxy] websocket socket error:', err.code || err.message)
            })
          })
          proxy.on('econnreset', (err) => {
            console.warn('[vite proxy] ECONNRESET:', err.message)
          })
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.js'],
  },
})

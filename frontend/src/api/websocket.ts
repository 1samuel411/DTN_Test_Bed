/**
 * WebSocket client with auto-reconnect.
 * Connects to the API server's /ws endpoint.
 */
import { useEffect, useRef, useState } from 'react';
import { DASHBOARD_WEBSOCKET_URL } from '../lib/dashboardEndpoints';
import { WSMessage } from '../types';

type MessageHandler = (msg: WSMessage) => void;

export function useWebSocket(
  onMessage: MessageHandler,
): 'connecting' | 'open' | 'closed' {
  const wsRef = useRef<WebSocket | null>(null);
  const retriesRef = useRef(0);
  const onMessageRef = useRef(onMessage);
  const [connectionState, setConnectionState] = useState<'connecting' | 'open' | 'closed'>(
    'connecting',
  );

  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  useEffect(() => {
    const cancelledRef = { current: false };
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (cancelledRef.current) {
        return;
      }

      setConnectionState('connecting');
      const ws = new WebSocket(DASHBOARD_WEBSOCKET_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        if (cancelledRef.current) {
          ws.close();
          return;
        }

        retriesRef.current = 0;
        setConnectionState('open');
      };

      ws.onmessage = (e) => {
        try {
          const msg: WSMessage = JSON.parse(e.data);
          onMessageRef.current(msg);
        } catch (err) {
          console.warn('[WS] parse error', err);
        }
      };

      ws.onerror = (e) => {
        console.warn('[WS] error', e);
      };

      ws.onclose = () => {
        wsRef.current = null;
        if (cancelledRef.current) {
          return;
        }

        const delay = Math.min(1000 * 2 ** retriesRef.current, 30_000);
        retriesRef.current += 1;
        setConnectionState('connecting');
        reconnectTimer = setTimeout(connect, delay);
      };
    };

    connect();

    return () => {
      cancelledRef.current = true;
      if (reconnectTimer !== null) {
        clearTimeout(reconnectTimer);
      }

      const w = wsRef.current;
      wsRef.current = null;
      w?.close();
    };
  }, []);

  return connectionState;
}

/**
 * URLs the dashboard uses to reach the Mac backend (REST + WebSocket).
 * Set VITE_API_URL to the Mac API origin (e.g. http://192.168.x.x:8080).
 * If VITE_WS_URL is omitted, the WebSocket URL is derived from VITE_API_URL (http→ws, https→wss)
 * so REST and the live stream stay aligned.
 */
export const API_BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8080';

const explicitWs = import.meta.env.VITE_WS_URL;

function httpOriginToWebSocketOrigin(httpUrl: string): string {
  try {
    const u = new URL(httpUrl);
    u.protocol = u.protocol === 'https:' ? 'wss:' : 'ws:';
    return u.origin;
  } catch {
    return 'ws://localhost:8080';
  }
}

const WS_BASE =
  typeof explicitWs === 'string' && explicitWs.trim() !== ''
    ? explicitWs.trim().replace(/\/$/, '')
    : httpOriginToWebSocketOrigin(API_BASE_URL);

export const DASHBOARD_WEBSOCKET_URL = `${WS_BASE}/ws`;

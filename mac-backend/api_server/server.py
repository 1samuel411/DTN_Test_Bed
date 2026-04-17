"""
API Server — FastAPI + WebSocket.

REST endpoints:
  GET /api/status          — latest Pi status report
  GET /api/telemetry       — last N altitude telemetry messages
  GET /api/results         — last N accepted telemetry results
  GET /api/events          — last N events (telemetry + GPS + failover + queue)
  GET /api/dtn/counters    — DTN-level traffic counters
  GET /api/metrics         — rolling latency / delivery / deadline metrics
  GET /api/metrics/experiment/distribution — grouped outcomes by mode+emulation
  GET /api/experiment-recording-runs — persisted emulation recording snapshots (SQLite)
  POST /api/experiment-recording-runs — store a snapshot when a recording stops
  POST /api/command        — forward a control command to the Pi via Config Server

WebSocket:
  ws://<host>:<port>/ws    — broadcasts:
      { type: "pi_status",  data: PiStatusReport }
      { type: "metrics",    data: TelemetryMetrics }
      { type: "experiment_metrics", data: ExperimentMetrics }
      { type: "experiment_distribution", data: ExperimentDistributionMetrics }
      { type: "telemetry_result", data: RecentTelemetryResult }
      { type: "bundle",     data: AltitudeTelemetry | GPSStatusMessage }
      { type: "event",      data: Event }
"""

import asyncio
import json
import logging
from typing import Callable, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from shared.schemas import ExperimentRecordingRunCreate

logger = logging.getLogger(__name__)


class APIServer:
    def __init__(self, store, config_server_send: Callable, host: str, port: int) -> None:
        self._store      = store
        self._cmd_send   = config_server_send
        self._host       = host
        self._port       = port
        self._clients: Set[WebSocket] = set()
        self._app        = self._build_app()

    @property
    def app(self) -> FastAPI:
        return self._app

    # ── WebSocket broadcast (called by Store) ─────────────────────────────────

    def broadcast(self, payload: dict) -> None:
        """Push to all connected WS clients. Fire-and-forget (no await)."""
        if not self._clients:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("WS broadcast skipped: no running event loop")
            return
        raw = json.dumps(payload)
        for ws in list(self._clients):
            loop.create_task(self._send_to_client(ws, raw))

    async def _send_to_client(self, ws: WebSocket, raw: str) -> None:
        try:
            await ws.send_text(raw)
        except Exception as e:
            self._clients.discard(ws)
            logger.debug("WS broadcast dropped closed client: %s", e)

    # ── FastAPI app ───────────────────────────────────────────────────────────

    def _build_app(self) -> FastAPI:
        app = FastAPI(title="DTN Testbed API")

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        @app.get("/api/status")
        async def get_status():
            s = self._store.get_pi_status()
            if s is None:
                return JSONResponse({"error": "no status yet"}, status_code=503)
            return s.model_dump()

        @app.get("/api/telemetry")
        async def get_telemetry(limit: int = 50):
            msgs = self._store.get_recent_telemetry(limit=limit)
            return [m.model_dump() for m in msgs]

        @app.get("/api/results")
        async def get_results(limit: int = 50):
            rows = self._store.get_recent_results(limit=limit)
            return [r.model_dump() for r in rows]

        @app.get("/api/events")
        async def get_events(limit: int = 100):
            evs = self._store.get_recent_events(limit=limit)
            return [e.model_dump() for e in evs]

        @app.get("/api/dtn/counters")
        async def get_dtn_counters():
            return self._store.get_dtn_counters().model_dump()

        @app.get("/api/metrics")
        async def get_metrics():
            return self._store.get_telemetry_metrics().model_dump()

        @app.get("/api/metrics/experiment")
        async def get_experiment_metrics():
            return self._store.get_experiment_metrics().model_dump()

        @app.get("/api/metrics/experiment/distribution")
        async def get_experiment_distribution_metrics():
            return self._store.get_experiment_distribution_metrics().model_dump()

        @app.get("/api/experiment-recording-runs")
        async def list_experiment_recording_runs(limit: int = 20):
            runs = self._store.list_experiment_recording_runs(limit=limit)
            return [r.model_dump() for r in runs]

        @app.post("/api/experiment-recording-runs")
        async def create_experiment_recording_run(body: dict):
            try:
                payload = ExperimentRecordingRunCreate.model_validate(body)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            run_id = self._store.save_experiment_recording_run(payload)
            return {"id": run_id}

        @app.post("/api/command")
        async def post_command(body: dict):
            """
            Forward a control command to the Pi via the Config Server's WebSocket.
            Body must be a valid MgmtCommand JSON object with a 'cmd' field.
            """
            try:
                await self._cmd_send(body)
                return {"ok": True}
            except Exception as e:
                logger.error("Command forward error: %s", e)
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.websocket("/ws")
        async def ws_endpoint(websocket: WebSocket):
            await websocket.accept()
            self._clients.add(websocket)
            logger.info("WS client connected (%d total)", len(self._clients))

            # Send current state immediately on connect
            status = self._store.get_pi_status()
            if status:
                await websocket.send_text(
                    json.dumps({"type": "pi_status", "data": status.model_dump()})
                )
            await websocket.send_text(
                json.dumps({"type": "dtn_counters", "data": self._store.get_dtn_counters().model_dump()})
            )
            await websocket.send_text(
                json.dumps({"type": "metrics", "data": self._store.get_telemetry_metrics().model_dump()})
            )
            await websocket.send_text(
                json.dumps({"type": "experiment_metrics",
                            "data": self._store.get_experiment_metrics().model_dump()})
            )
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "experiment_distribution",
                        "data": self._store.get_experiment_distribution_metrics().model_dump(),
                    }
                )
            )
            for ev in self._store.get_recent_events(limit=20):
                await websocket.send_text(
                    json.dumps({"type": "event", "data": ev.model_dump()})
                )
            recent = self._store.get_recent_telemetry(limit=20)
            for m in recent:
                await websocket.send_text(
                    json.dumps({"type": "bundle", "data": m.model_dump()})
                )
            for row in self._store.get_recent_results(limit=20):
                await websocket.send_text(
                    json.dumps({"type": "telemetry_result", "data": row.model_dump()})
                )

            try:
                async for _ in websocket.iter_text():
                    pass  # Client messages not needed (read-only WS)
            except WebSocketDisconnect:
                pass
            finally:
                self._clients.discard(websocket)
                logger.info("WS client disconnected (%d remaining)", len(self._clients))

        return app

    async def run(self) -> None:
        import uvicorn
        config = uvicorn.Config(
            self._app,
            host    = self._host,
            port    = self._port,
            log_level = "info",
        )
        server = uvicorn.Server(config)
        await server.serve()

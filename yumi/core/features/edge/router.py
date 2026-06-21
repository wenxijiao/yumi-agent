"""Edge websocket routes."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket
from yumi.core.features.edge.api import handle_edge_peer
from yumi.core.features.edge.peers import LocalEdgePeer

router = APIRouter()


@router.websocket("/ws/edge")
async def websocket_edge_endpoint(websocket: WebSocket):
    # Edge devices register their tools here without authenticating: this is your
    # own machine / LAN hosting your own agent, so registration is open by design
    # (the server binds 127.0.0.1 by default — see SECURITY.md). Run it on a
    # trusted network; an edge name already in use is still rejected (close 4409).
    await websocket.accept()
    peer = LocalEdgePeer(websocket)
    await handle_edge_peer(peer)

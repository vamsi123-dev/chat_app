from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

router = APIRouter()

# Store both connections and online status
status_connections = {}
online_users = set()

@router.websocket("/ws/status/")
async def websocket_status(websocket: WebSocket, token: str = Query(...)):
    from app.core.security import decode_access_token
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        await websocket.close(code=1008)
        return
    
    user_id = int(payload["sub"])
    await websocket.accept()
    
    # Add this connection to active connections and mark user as online
    status_connections[user_id] = websocket
    online_users.add(user_id)
    
    try:
        # Send the current online status of all users to the new connection
        for online_user_id in online_users:
            await websocket.send_json({
                "user_id": online_user_id,
                "status": "online"
            })
        
        # Broadcast to all other connections that this user is online
        for other_id, ws in status_connections.items():
            if other_id != user_id:  # Don't send to self
                await ws.send_json({
                    "user_id": user_id,
                    "status": "online"
                })
        
        while True:
            data = await websocket.receive_json()
            # Broadcast status updates to all connections except self
            for other_id, ws in status_connections.items():
                if other_id != user_id:  # Don't send to self
                    await ws.send_json({"user_id": user_id, **data})
                    
    except WebSocketDisconnect:
        # Remove user from connections and online users
        if user_id in status_connections:
            del status_connections[user_id]
        online_users.discard(user_id)
        
        # Notify all remaining users that this user is offline
        for ws in status_connections.values():
            await ws.send_json({
                "user_id": user_id,
                "status": "offline"
            }) 
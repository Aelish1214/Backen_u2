import os
import sys
from fastapi import FastAPI, Request
from dotenv import load_dotenv
from aiortc import RTCPeerConnection, RTCSessionDescription

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "app")))
load_dotenv()

from app.main import INAIApplication
from inai_project.main import AuthApplication
from inai_project.app.history.history_routes import router as history_router
from inai_project.app.history.history_manager import HistoryManager
from app.logger import Logger

logger = Logger()

history_manager = HistoryManager(
    db_url=os.getenv("DATABASE_URL"),
    bucket_name=os.getenv("AWS_BUCKET_NAME"),
    aws_access_key=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region=os.getenv("AWS_REGION"),
    logger=logger
)

app = FastAPI()
pcs = {}  # store active peer connections

# WebRTC Offer endpoint
@app.post("/webrtc/offer/{user_id}")
async def webrtc_offer(user_id: str, request: Request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    pc = RTCPeerConnection()
    pcs[user_id] = pc

    # Create data channel for text messages
    @pc.on("datachannel")
    def on_datachannel(channel):
        @channel.on("message")
        async def on_message(message):
            import json
            try:
                msg_data = json.loads(message)
                text = msg_data.get("text", "")
                mode = msg_data.get("mode", "friend")
                # Simple echo response; replace with INAI AI logic
                response_text = f"[{mode}] You said: {text}"
                response_audio = None  # Base64 audio if TTS used
                channel.send(json.dumps({"text": response_text, "audio": response_audio}))
            except Exception as e:
                print("DataChannel message error:", e)

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}

# ICE candidate endpoint
@app.post("/webrtc/ice/{user_id}")
async def ice_candidate(user_id: str, request: Request):
    data = await request.json()
    candidate = data.get("candidate")
    if candidate and user_id in pcs:
        await pcs[user_id].addIceCandidate(candidate)
    return {"status": "ok"}

# Mount existing apps
auth_app = AuthApplication().get_app()
app.mount("/auth", auth_app)

app.include_router(history_router, prefix="/history")

inai_app = INAIApplication(history_manager)
app.mount("/", inai_app.app)

@app.get("/health")
def health_check():
    return {"status": "INAI running at root :rocket:"}

@app.on_event("startup")
async def startup():
    await history_manager.init_db()
    app.state.history_manager = history_manager

@app.on_event("shutdown")
async def shutdown():
    await history_manager.close()
    # close all peer connections
    for pc in pcs.values():
        await pc.close()
    pcs.clear()

if __name__ == "__main__":
    import uvicorn
    host = "0.0.0.0"
    port = 5200
    logger.info(f"🚀 Starting INAI on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, reload=True)

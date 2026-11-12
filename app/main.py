from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field
import uuid

app = FastAPI()

class NotificationRequest(BaseModel):
    channel: str
    source: str
    reference_id: str = None
    sms: dict = None
    push: dict = None
    email: dict = None

@app.post("/v1/notifications")
async def create_notification(
    notification: NotificationRequest,
    x_api_key: str = Header(None),
    idempotency_key: str = Header(None)
):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Validate channel and payload
    if notification.channel not in ["sms", "push", "email"]:
        raise HTTPException(status_code=422, detail="Invalid channel")

    # Generate send_id
    send_id = str(uuid.uuid4())

    # Simulate storing in database and publishing to Kafka
    # In a real implementation, you would insert into the database and publish to Kafka here

    return {"send_id": send_id, "status": "queued", "channel": notification.channel}

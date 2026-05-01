from fastapi import FastAPI
import bot

app = FastAPI()

# health check
@app.get("/v1/healthz")
def health():
    return {"status": "ok"}

# metadata
@app.get("/v1/metadata")
def metadata():
    return {
        "team_name": "Your Team",
        "members": ["Your Name"]
    }

# context (can be dummy if not needed)
@app.post("/v1/context")
def context(data: dict):
    return {"status": "received"}

# MAIN endpoint (MOST IMPORTANT)
@app.post("/v1/tick")
def tick(data: dict):
    result = bot.compose(
        data["category"],
        data["merchant"],
        data["trigger"],
        data.get("customer")
    )
    return result

# reply handler
@app.post("/v1/reply")
def reply(data: dict):
    return {"message": "Reply handled"}
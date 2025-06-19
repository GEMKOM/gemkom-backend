from fastapi import FastAPI, Request
from pydantic import BaseModel
from datetime import datetime

app = FastAPI()

# In-memory "database" (will reset every deploy)
timers = {}
counter = 1

class TimerStart(BaseModel):
    user_id: str
    issue_key: str
    machine: str = ""
    job_no: str = ""
    start_time: str = None  # Optional override

class TimerStop(BaseModel):
    id: int
    finish_time: str = None

@app.post("/start-timer")
def start_timer(data: TimerStart):
    global counter
    timer_id = counter
    counter += 1
    timers[timer_id] = {
        "id": timer_id,
        "user_id": data.user_id,
        "issue_key": data.issue_key,
        "machine": data.machine,
        "job_no": data.job_no,
        "start_time": data.start_time or datetime.utcnow().isoformat(),
        "finish_time": None
    }
    return timers[timer_id]

@app.post("/stop-timer")
def stop_timer(data: TimerStop):
    if data.id not in timers:
        return {"error": "Timer not found"}
    timers[data.id]["finish_time"] = data.finish_time or datetime.utcnow().isoformat()
    return timers[data.id]

@app.get("/active-timers")
def list_active():
    return [t for t in timers.values() if t["finish_time"] is None]

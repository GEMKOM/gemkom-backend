from fastapi import FastAPI
from pydantic import BaseModel
from datetime import datetime
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

conn = psycopg2.connect(os.getenv("DB_URL"))
conn.autocommit = True

class TimerStart(BaseModel):
    user_id: str
    issue_key: str
    machine: str = ""
    job_no: str = ""
    start_time: str = None

@app.post("/start-timer")
def start_timer(data: TimerStart):
    cur = conn.cursor()
    start_time = data.start_time or datetime.utcnow().isoformat()
    cur.execute("""
        INSERT INTO timers (user_id, issue_key, machine, job_no, start_time)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
    """, (data.user_id, data.issue_key, data.machine, data.job_no, start_time))
    timer_id = cur.fetchone()[0]
    return { "id": timer_id, "start_time": start_time }

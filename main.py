from fastapi import FastAPI, Request
from pydantic import BaseModel
from datetime import datetime
import psycopg2
import os

app = FastAPI()

# Connect to Supabase PostgreSQL
conn = psycopg2.connect(os.environ["DB_URL"])
conn.autocommit = True


# ---------------------------
# Request Body Schemas
# ---------------------------

class TimerStart(BaseModel):
    user_id: str
    issue_key: str
    start_time: str
    machine: str = ""
    job_no: str = ""
    image_no: str = ""
    position_no: str = ""
    quantity: int = None


class TimerStop(BaseModel):
    user_id: str
    finish_time: str
    comment: str = None
    synced_to_jira: bool = False
    machine: str = None
    timer_id: int


class TimerManual(BaseModel):
    user_id: str
    issue_key: str
    start_time: str
    finish_time: str = None
    machine: str = ""
    job_no: str = ""
    image_no: str = ""
    position_no: str = ""
    quantity: int = None


# ---------------------------
# Endpoints
# ---------------------------

@app.post("/start-timer")
def start_timer(data: TimerStart):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO timers (user_id, issue_key, start_time, machine, job_no, image_no, position_no, quantity)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id;
    """, (
        data.user_id,
        data.issue_key,
        data.start_time,
        data.machine,
        data.job_no,
        data.image_no,
        data.position_no,
        data.quantity
    ))
    row = cur.fetchone()
    return { "id": row[0] }


@app.post("/stop-timer")
def stop_timer(data: TimerStop):
    cur = conn.cursor()
    cur.execute("""
        UPDATE timers
        SET finish_time = %s, comment = %s, synced_to_jira = %s, machine = %s
        WHERE id = %s;
    """, (
        data.finish_time,
        data.comment,
        int(data.synced_to_jira),
        data.machine,
        data.timer_id
    ))
    return { "message": "Timer stopped and updated." }


@app.post("/manual-entry")
def manual_entry(data: TimerManual):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO timers (
            user_id, issue_key, start_time, finish_time, machine,
            job_no, image_no, position_no, quantity, manual_entry
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
        RETURNING id;
    """, (
        data.user_id,
        data.issue_key,
        data.start_time,
        data.finish_time,
        data.machine,
        data.job_no,
        data.image_no,
        data.position_no,
        data.quantity
    ))
    row = cur.fetchone()
    return { "id": row[0] }


@app.get("/list-timers")
def list_timers(request: Request):
    cur = conn.cursor()
    params = request.query_params
    active = params.get("active")
    user = params.get("user")
    issue_key = params.get("issue_key")

    query = "SELECT * FROM timers"
    conditions = []
    values = []

    if active == "true":
        conditions.append("finish_time IS NULL")
    elif active == "false":
        conditions.append("finish_time IS NOT NULL")

    if user:
        conditions.append("user_id = %s")
        values.append(user)

    if issue_key:
        conditions.append("issue_key = %s")
        values.append(issue_key)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY start_time DESC"
    cur.execute(query, values)
    rows = cur.fetchall()

    return [
        {
            "id": r[0],
            "user_id": r[1],
            "issue_key": r[2],
            "start_time": r[3],
            "finish_time": r[4],
            "machine": r[5],
            "job_no": r[6],
            "image_no": r[7],
            "position_no": r[8],
            "quantity": r[9],
            "manual_entry": r[10] if len(r) > 10 else None,
            "comment": r[11] if len(r) > 11 else None,
            "synced_to_jira": r[12] if len(r) > 12 else None
        }
        for r in rows
    ]


@app.get("/now")
def get_now():
    return { "now": datetime.utcnow().isoformat() }

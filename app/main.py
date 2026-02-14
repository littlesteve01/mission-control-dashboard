import os
import uuid
from datetime import datetime, date, timedelta
from typing import List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.requests import Request
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.database import get_db, init_db, engine
from app.models import Task, SubTask, TokenUsage, ApiCall, CronJob, DailySummary, Base
from app.schemas import (
    TaskCreate, TaskUpdate, TaskResponse, 
    SubTaskCreate, SubTaskUpdate,
    TokenUsageCreate, ApiCallCreate,
    DashboardStats, TaskWithSubtasks
)

# Import new services for OpenClaw data
from app.services import SessionParser, StatsAggregator, CronReader

# Startup time for uptime calculation
STARTUP_TIME = datetime.now()

# Initialize services (lazy loading)
_session_parser: Optional[SessionParser] = None
_stats_aggregator: Optional[StatsAggregator] = None
_cron_reader: Optional[CronReader] = None

def get_session_parser() -> SessionParser:
    global _session_parser
    if _session_parser is None:
        _session_parser = SessionParser()
    return _session_parser

def get_stats_aggregator() -> StatsAggregator:
    global _stats_aggregator
    if _stats_aggregator is None:
        _stats_aggregator = StatsAggregator(get_session_parser())
    return _stats_aggregator

def get_cron_reader() -> CronReader:
    global _cron_reader
    if _cron_reader is None:
        _cron_reader = CronReader()
    return _cron_reader

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    Base.metadata.create_all(bind=engine)
    yield
    # Shutdown

app = FastAPI(
    title="🎯 Mission Control",
    description="Clawdi's Activity Dashboard",
    version="2.0.0",
    lifespan=lifespan
)

# Static files and templates
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# ============ DASHBOARD ============

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """Main dashboard view"""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/stats", response_model=DashboardStats)
async def get_stats(db: Session = Depends(get_db)):
    """Get dashboard statistics - uses real OpenClaw session data"""
    today = date.today().isoformat()
    today_start = datetime.combine(date.today(), datetime.min.time())
    
    # Get real token/cost data from OpenClaw sessions
    aggregator = get_stats_aggregator()
    today_stats = aggregator.get_today_stats()
    
    # Task counts (from our DB - for tracked tasks)
    tasks_today = db.query(Task).filter(Task.created_at >= today_start).count()
    completed_today = db.query(Task).filter(
        Task.created_at >= today_start, 
        Task.status == "completed"
    ).count()
    failed_today = db.query(Task).filter(
        Task.created_at >= today_start, 
        Task.status == "failed"
    ).count()
    running_now = db.query(Task).filter(Task.status == "running").count()
    
    # Use real token data from sessions
    tokens_input = today_stats['tokens_input']
    tokens_output = today_stats['tokens_output']
    cost_today = today_stats['cost_total_usd']
    
    # API calls from real data
    api_calls_today = today_stats['api_calls']
    
    # Messages from real session data (only real Telegram messages, not system events)
    parser = get_session_parser()
    message_counts = parser.count_messages(days=1)
    messages_today = message_counts['user']  # Only real user messages from Telegram
    
    # Uptime
    uptime = datetime.now() - STARTUP_TIME
    uptime_hours = uptime.total_seconds() / 3600
    
    return DashboardStats(
        tasks_today=tasks_today,
        completed_today=completed_today,
        failed_today=failed_today,
        running_now=running_now,
        tokens_today=tokens_input + tokens_output,
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        cost_today_usd=round(cost_today, 4),
        api_calls_today=api_calls_today,
        api_errors_today=0,  # Not tracked in sessions
        messages_today=messages_today,
        current_session="agent:main:main",
        uptime_hours=round(uptime_hours, 2)
    )

# ============ TOKEN USAGE (Real Data) ============

@app.get("/api/tokens/summary")
async def get_token_summary(days: Optional[int] = Query(None, ge=0, le=365)):
    """Get token usage summary from real OpenClaw sessions. days=0 or omitted = all data"""
    aggregator = get_stats_aggregator()
    # days=0 or None means all data
    actual_days = None if days is None or days == 0 else days
    daily_stats = aggregator.get_daily_stats(days=actual_days)
    
    return daily_stats

@app.get("/api/tokens/total")
async def get_token_total():
    """Get total token/cost stats over all time"""
    aggregator = get_stats_aggregator()
    return aggregator.get_total_stats()

@app.get("/api/tokens/today")
async def get_tokens_today():
    """Get today's token usage details"""
    aggregator = get_stats_aggregator()
    return aggregator.get_today_stats()

# ============ PROVIDER STATS (Real Data) ============

@app.get("/api/calls/by-provider")
async def get_calls_by_provider(days: int = Query(1, ge=1, le=30)):
    """Get API call/token counts by provider from real OpenClaw sessions"""
    aggregator = get_stats_aggregator()
    provider_stats = aggregator.get_provider_stats(days=days)
    
    return provider_stats

# ============ SESSIONS ============

@app.get("/api/sessions")
async def get_sessions(days: int = Query(7, ge=1, le=30), limit: int = Query(20, ge=1, le=100)):
    """Get recent sessions with usage stats"""
    aggregator = get_stats_aggregator()
    return aggregator.get_session_stats(days=days, limit=limit)

# ============ CRON JOBS (Real Data) ============

@app.get("/api/cron")
async def get_cron_jobs():
    """Get cron jobs from OpenClaw cron config"""
    reader = get_cron_reader()
    jobs = reader.get_jobs(include_disabled=False)
    
    return [
        {
            'job_id': j.id,
            'name': j.name,
            'schedule': f"{j.schedule_kind}: {j.schedule_expr}",
            'schedule_kind': j.schedule_kind,
            'schedule_expr': j.schedule_expr,
            'timezone': j.timezone,
            'last_run': j.last_run.isoformat() if j.last_run else None,
            'next_run': j.next_run.isoformat() if j.next_run else None,
            'last_status': j.last_status,
            'last_duration_ms': j.last_duration_ms,
            'enabled': j.enabled,
            'session_target': j.session_target,
            'payload_kind': j.payload_kind
        }
        for j in jobs
    ]

@app.get("/api/cron/summary")
async def get_cron_summary():
    """Get cron jobs summary"""
    reader = get_cron_reader()
    return reader.get_summary()

@app.get("/api/cron/next")
async def get_next_cron_jobs(count: int = Query(5, ge=1, le=20)):
    """Get next scheduled cron jobs"""
    reader = get_cron_reader()
    return reader.get_next_jobs(count=count)

@app.get("/api/cron/recent")
async def get_recent_cron_runs(count: int = Query(10, ge=1, le=50)):
    """Get recent cron job runs"""
    reader = get_cron_reader()
    return reader.get_recent_runs(count=count)

# ============ DASHBOARD DATA (Combined) ============

@app.get("/api/dashboard")
async def get_dashboard_data(db: Session = Depends(get_db)):
    """Get all dashboard data in one call"""
    aggregator = get_stats_aggregator()
    cron_reader = get_cron_reader()
    
    today_start = datetime.combine(date.today(), datetime.min.time())
    
    # Get session-based stats
    dashboard_stats = aggregator.get_dashboard_stats()
    
    # Get task counts from DB
    tasks_today = db.query(Task).filter(Task.created_at >= today_start).count()
    running_now = db.query(Task).filter(Task.status == "running").count()
    
    # Cron summary
    cron_summary = cron_reader.get_summary()
    
    # Uptime
    uptime = datetime.now() - STARTUP_TIME
    
    return {
        'stats': {
            'tokens_today': dashboard_stats['today']['tokens_total'],
            'tokens_input': dashboard_stats['today']['tokens_input'],
            'tokens_output': dashboard_stats['today']['tokens_output'],
            'cost_today_usd': dashboard_stats['today']['cost_total_usd'],
            'api_calls_today': dashboard_stats['today']['api_calls'],
            'tasks_today': tasks_today,
            'running_now': running_now
        },
        'token_history': dashboard_stats['daily_history'],
        'providers': dashboard_stats['providers'],
        'cron': cron_summary,
        'uptime_seconds': int(uptime.total_seconds()),
        'timestamp': datetime.now().isoformat()
    }

# ============ TASKS ============

@app.post("/api/tasks", response_model=TaskResponse)
async def create_task(task: TaskCreate, db: Session = Depends(get_db)):
    """Create a new task"""
    task_id = str(uuid.uuid4())[:8]
    db_task = Task(
        task_id=task_id,
        name=task.name,
        description=task.description,
        category=task.category,
        trigger=task.trigger,
        tool_name=task.tool_name,
        tool_params=task.tool_params,
        session_key=task.session_key,
        message_id=task.message_id,
        status="running",
        started_at=datetime.now()
    )
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    return db_task

@app.patch("/api/tasks/{task_id}")
async def update_task(task_id: str, update: TaskUpdate, db: Session = Depends(get_db)):
    """Update task status"""
    task = db.query(Task).filter(Task.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    for key, value in update.model_dump(exclude_unset=True).items():
        setattr(task, key, value)
    
    if update.status == "completed" and not task.completed_at:
        task.completed_at = datetime.now()
        if task.started_at:
            task.duration_ms = int((task.completed_at - task.started_at).total_seconds() * 1000)
    
    db.commit()
    return {"ok": True, "task_id": task_id}

@app.get("/api/tasks", response_model=List[TaskResponse])
async def get_tasks(
    status: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db)
):
    """Get tasks with optional filters"""
    query = db.query(Task)
    if status:
        query = query.filter(Task.status == status)
    if category:
        query = query.filter(Task.category == category)
    
    return query.order_by(desc(Task.created_at)).limit(limit).all()

@app.get("/api/tasks/running", response_model=List[TaskWithSubtasks])
async def get_running_tasks(db: Session = Depends(get_db)):
    """Get currently running tasks with subtasks"""
    tasks = db.query(Task).filter(Task.status == "running").all()
    result = []
    for task in tasks:
        subtasks = db.query(SubTask).filter(SubTask.task_id == task.task_id).order_by(SubTask.order_idx).all()
        task_dict = TaskWithSubtasks.model_validate(task)
        task_dict.subtasks = [{"name": s.name, "status": s.status, "duration_ms": s.duration_ms} for s in subtasks]
        result.append(task_dict)
    return result

@app.get("/api/tasks/recent")
async def get_recent_tasks(limit: int = 20, db: Session = Depends(get_db)):
    """Get recent completed tasks"""
    tasks = db.query(Task).filter(
        Task.status.in_(["completed", "failed"])
    ).order_by(desc(Task.completed_at)).limit(limit).all()
    
    return [{
        "task_id": t.task_id,
        "name": t.name,
        "status": t.status,
        "category": t.category,
        "tool_name": t.tool_name,
        "duration_ms": t.duration_ms,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        "result_summary": t.result_summary,
        "error_message": t.error_message
    } for t in tasks]

# ============ SUBTASKS ============

@app.post("/api/subtasks")
async def create_subtask(subtask: SubTaskCreate, db: Session = Depends(get_db)):
    """Add a subtask to a task"""
    db_subtask = SubTask(**subtask.model_dump(), status="running")
    db.add(db_subtask)
    db.commit()
    return {"ok": True, "id": db_subtask.id}

@app.patch("/api/subtasks/{subtask_id}")
async def update_subtask(subtask_id: int, update: SubTaskUpdate, db: Session = Depends(get_db)):
    """Update subtask"""
    subtask = db.query(SubTask).filter(SubTask.id == subtask_id).first()
    if not subtask:
        raise HTTPException(status_code=404, detail="Subtask not found")
    
    for key, value in update.model_dump(exclude_unset=True).items():
        setattr(subtask, key, value)
    db.commit()
    return {"ok": True}

# ============ MANUAL TOKEN/API LOGGING (Legacy) ============

@app.post("/api/tokens")
async def log_token_usage(usage: TokenUsageCreate, db: Session = Depends(get_db)):
    """Log token usage (legacy - real data comes from sessions)"""
    db_usage = TokenUsage(**usage.model_dump())
    db.add(db_usage)
    db.commit()
    return {"ok": True, "id": db_usage.id}

@app.post("/api/calls")
async def log_api_call(call: ApiCallCreate, db: Session = Depends(get_db)):
    """Log an API call"""
    db_call = ApiCall(**call.model_dump())
    db.add(db_call)
    db.commit()
    return {"ok": True, "id": db_call.id}

# ============ CACHE MANAGEMENT ============

@app.post("/api/cache/clear")
async def clear_caches():
    """Clear all data caches (forces re-read of session files)"""
    get_stats_aggregator().clear_cache()
    get_cron_reader().clear_cache()
    return {"ok": True, "message": "Caches cleared"}

# ============ HEALTH ============

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "ok",
        "uptime_seconds": int((datetime.now() - STARTUP_TIME).total_seconds()),
        "version": "2.0.0",
        "data_source": "openclaw_sessions"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8087)

from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, JSON
from sqlalchemy.sql import func
from app.database import Base

class Task(Base):
    """Individual task/activity log"""
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(50), unique=True, index=True)  # UUID
    name = Column(String(200), nullable=False)
    description = Column(Text)
    status = Column(String(20), default="pending")  # pending, running, completed, failed
    category = Column(String(50))  # tool_call, cron, user_request, proactive
    trigger = Column(String(50))  # user, cron, heartbeat, system
    
    # Timing
    started_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime)
    duration_ms = Column(Integer)
    
    # Details
    tool_name = Column(String(50))
    tool_params = Column(JSON)
    result_summary = Column(Text)
    error_message = Column(Text)
    
    # Context
    session_key = Column(String(100))
    message_id = Column(String(50))
    
    created_at = Column(DateTime, server_default=func.now())

class SubTask(Base):
    """Sub-steps within a task"""
    __tablename__ = "subtasks"
    
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(50), index=True)
    name = Column(String(200))
    status = Column(String(20), default="pending")
    duration_ms = Column(Integer)
    result = Column(Text)
    order_idx = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())

class TokenUsage(Base):
    """Token consumption tracking"""
    __tablename__ = "token_usage"
    
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(50), index=True)
    session_key = Column(String(100))
    
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cache_read_tokens = Column(Integer, default=0)
    cache_write_tokens = Column(Integer, default=0)
    
    model = Column(String(100))
    provider = Column(String(50))
    
    # Cost estimate (USD)
    cost_usd = Column(Float, default=0.0)
    
    created_at = Column(DateTime, server_default=func.now())

class ApiCall(Base):
    """External API call tracking"""
    __tablename__ = "api_calls"
    
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(50), index=True)
    
    provider = Column(String(50))  # anthropic, brave, coingecko, protonmail, telegram, etc.
    endpoint = Column(String(200))
    method = Column(String(10))
    
    status_code = Column(Integer)
    success = Column(Boolean, default=True)
    latency_ms = Column(Integer)
    error = Column(Text)
    
    created_at = Column(DateTime, server_default=func.now())

class CronJob(Base):
    """Cron job status tracking"""
    __tablename__ = "cron_jobs"
    
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String(50), unique=True, index=True)
    name = Column(String(200))
    schedule = Column(String(100))
    
    last_run = Column(DateTime)
    next_run = Column(DateTime)
    last_status = Column(String(20))
    run_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

class DailySummary(Base):
    """Daily aggregated stats"""
    __tablename__ = "daily_summaries"
    
    id = Column(Integer, primary_key=True, index=True)
    date = Column(String(10), unique=True, index=True)  # YYYY-MM-DD
    
    total_tasks = Column(Integer, default=0)
    completed_tasks = Column(Integer, default=0)
    failed_tasks = Column(Integer, default=0)
    
    total_tokens = Column(Integer, default=0)
    total_cost_usd = Column(Float, default=0.0)
    
    api_calls = Column(Integer, default=0)
    messages_sent = Column(Integer, default=0)
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())


# ============ NEW FEATURES ============

class KanbanTask(Base):
    """Kanban board task"""
    __tablename__ = "kanban_tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    column = Column(String(20), default="todo")  # todo, inprogress, done, archived
    order_idx = Column(Integer, default=0)
    color = Column(String(20), default="default")  # default, red, yellow, green, blue, purple
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class AgentNote(Base):
    """Notes for agent to check during heartbeats"""
    __tablename__ = "agent_notes"
    
    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text, nullable=False)
    priority = Column(String(20), default="normal")  # low, normal, high, urgent
    is_read = Column(Boolean, default=False)
    read_at = Column(DateTime)
    
    created_at = Column(DateTime, server_default=func.now())


class ActionLog(Base):
    """Activity history log"""
    __tablename__ = "action_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    action = Column(String(50), nullable=False)  # task_created, task_moved, note_added, etc.
    details = Column(Text)
    icon = Column(String(10), default="📋")
    
    created_at = Column(DateTime, server_default=func.now())


class Deliverable(Base):
    """Quick access deliverables/folders"""
    __tablename__ = "deliverables"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    path = Column(String(500), nullable=False)
    icon = Column(String(10), default="📁")
    description = Column(String(200))
    order_idx = Column(Integer, default=0)
    
    created_at = Column(DateTime, server_default=func.now())

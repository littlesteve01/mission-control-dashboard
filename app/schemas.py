from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime

class TaskCreate(BaseModel):
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    trigger: Optional[str] = None
    tool_name: Optional[str] = None
    tool_params: Optional[dict] = None
    session_key: Optional[str] = None
    message_id: Optional[str] = None

class TaskUpdate(BaseModel):
    status: Optional[str] = None
    result_summary: Optional[str] = None
    error_message: Optional[str] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None

class SubTaskCreate(BaseModel):
    task_id: str
    name: str
    order_idx: Optional[int] = 0

class SubTaskUpdate(BaseModel):
    status: Optional[str] = None
    duration_ms: Optional[int] = None
    result: Optional[str] = None

class TokenUsageCreate(BaseModel):
    task_id: Optional[str] = None
    session_key: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    model: Optional[str] = None
    provider: Optional[str] = None
    cost_usd: float = 0.0

class ApiCallCreate(BaseModel):
    task_id: Optional[str] = None
    provider: str
    endpoint: Optional[str] = None
    method: Optional[str] = "GET"
    status_code: Optional[int] = None
    success: bool = True
    latency_ms: Optional[int] = None
    error: Optional[str] = None

class TaskResponse(BaseModel):
    id: int
    task_id: str
    name: str
    description: Optional[str]
    status: str
    category: Optional[str]
    trigger: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    duration_ms: Optional[int]
    tool_name: Optional[str]
    result_summary: Optional[str]
    error_message: Optional[str]
    
    class Config:
        from_attributes = True

class DashboardStats(BaseModel):
    # Today's stats
    tasks_today: int
    completed_today: int
    failed_today: int
    running_now: int
    
    # Token usage
    tokens_today: int
    tokens_input: int
    tokens_output: int
    cost_today_usd: float
    
    # API calls
    api_calls_today: int
    api_errors_today: int
    
    # Messages
    messages_today: int
    
    # Context
    current_session: Optional[str]
    uptime_hours: float

class TaskWithSubtasks(TaskResponse):
    subtasks: List[dict] = []

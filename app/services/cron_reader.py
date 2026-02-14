"""
Cron Reader - Reads OpenClaw cron jobs configuration
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import time

@dataclass
class CronJobInfo:
    """Cron job information"""
    id: str
    name: str
    enabled: bool
    schedule_kind: str  # 'cron', 'every', 'at'
    schedule_expr: str  # cron expression or interval
    timezone: Optional[str]
    next_run: Optional[datetime]
    last_run: Optional[datetime]
    last_status: Optional[str]
    last_duration_ms: Optional[int]
    session_target: str
    payload_kind: str
    payload_text: Optional[str]

class CronReader:
    """
    Reads cron job configuration from OpenClaw's cron directory.
    Implements caching to avoid frequent file reads.
    """
    
    CRON_DIR = os.path.expanduser("~/.openclaw/cron")
    JOBS_FILE = "jobs.json"
    CACHE_TTL = 30  # Cache valid for 30 seconds
    
    def __init__(self, cron_dir: Optional[str] = None):
        self.cron_dir = Path(cron_dir or self.CRON_DIR)
        self.jobs_file = self.cron_dir / self.JOBS_FILE
        self._cache: Optional[List[CronJobInfo]] = None
        self._cache_time: float = 0
        self._cache_mtime: float = 0
    
    def _is_cache_valid(self) -> bool:
        """Check if cache is still valid"""
        if self._cache is None:
            return False
        
        # Check time-based expiry
        if (time.time() - self._cache_time) > self.CACHE_TTL:
            return False
        
        # Check if file changed
        try:
            current_mtime = self.jobs_file.stat().st_mtime
            return current_mtime == self._cache_mtime
        except OSError:
            return False
    
    def _parse_schedule(self, schedule: dict) -> tuple[str, str, Optional[str]]:
        """
        Parse schedule object.
        
        Returns:
            Tuple of (kind, expression, timezone)
        """
        kind = schedule.get('kind', 'unknown')
        tz = schedule.get('tz')
        
        if kind == 'cron':
            expr = schedule.get('expr', '')
        elif kind == 'every':
            ms = schedule.get('everyMs', 0)
            if ms >= 3600000:
                expr = f"every {ms // 3600000}h"
            elif ms >= 60000:
                expr = f"every {ms // 60000}m"
            else:
                expr = f"every {ms // 1000}s"
        elif kind == 'at':
            at_ms = schedule.get('atMs', 0)
            try:
                at_dt = datetime.fromtimestamp(at_ms / 1000)
                expr = at_dt.strftime('%Y-%m-%d %H:%M')
            except (ValueError, OSError):
                expr = f"at {at_ms}"
        else:
            expr = str(schedule)
        
        return kind, expr, tz
    
    def _parse_timestamp_ms(self, ms: Optional[int]) -> Optional[datetime]:
        """Parse millisecond timestamp"""
        if not ms:
            return None
        try:
            return datetime.fromtimestamp(ms / 1000)
        except (ValueError, OSError):
            return None
    
    def get_jobs(self, include_disabled: bool = False) -> List[CronJobInfo]:
        """
        Get all cron jobs.
        
        Args:
            include_disabled: Include disabled jobs
            
        Returns:
            List of CronJobInfo objects
        """
        if self._is_cache_valid() and self._cache is not None:
            if include_disabled:
                return self._cache
            return [j for j in self._cache if j.enabled]
        
        if not self.jobs_file.exists():
            return []
        
        try:
            with open(self.jobs_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error reading cron jobs: {e}")
            return []
        
        jobs = []
        for job in data.get('jobs', []):
            schedule = job.get('schedule', {})
            kind, expr, tz = self._parse_schedule(schedule)
            
            state = job.get('state', {})
            payload = job.get('payload', {})
            
            # Extract payload text
            payload_text = None
            if payload.get('kind') == 'systemEvent':
                payload_text = payload.get('text', '')[:100]
            elif payload.get('kind') == 'agentTurn':
                payload_text = payload.get('message', '')[:100]
            
            job_info = CronJobInfo(
                id=job.get('id', ''),
                name=job.get('name', 'Unnamed'),
                enabled=job.get('enabled', True),
                schedule_kind=kind,
                schedule_expr=expr,
                timezone=tz,
                next_run=self._parse_timestamp_ms(state.get('nextRunAtMs')),
                last_run=self._parse_timestamp_ms(state.get('lastRunAtMs')),
                last_status=state.get('lastStatus'),
                last_duration_ms=state.get('lastDurationMs'),
                session_target=job.get('sessionTarget', 'main'),
                payload_kind=payload.get('kind', 'unknown'),
                payload_text=payload_text
            )
            jobs.append(job_info)
        
        # Update cache
        self._cache = jobs
        self._cache_time = time.time()
        try:
            self._cache_mtime = self.jobs_file.stat().st_mtime
        except OSError:
            self._cache_mtime = 0
        
        if include_disabled:
            return jobs
        return [j for j in jobs if j.enabled]
    
    def get_next_jobs(self, count: int = 5) -> List[Dict[str, Any]]:
        """
        Get the next N jobs scheduled to run.
        
        Args:
            count: Number of jobs to return
            
        Returns:
            List of job dicts with next run info
        """
        jobs = self.get_jobs(include_disabled=False)
        
        # Filter jobs with next_run and sort
        scheduled = [
            j for j in jobs 
            if j.next_run is not None
        ]
        scheduled.sort(key=lambda x: x.next_run)  # type: ignore
        
        now = datetime.now()
        
        return [
            {
                'id': j.id,
                'name': j.name,
                'schedule': f"{j.schedule_kind}: {j.schedule_expr}",
                'next_run': j.next_run.isoformat() if j.next_run else None,
                'minutes_until': int((j.next_run - now).total_seconds() / 60) if j.next_run else None,
                'last_status': j.last_status
            }
            for j in scheduled[:count]
        ]
    
    def get_recent_runs(self, count: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent job runs.
        
        Args:
            count: Number of runs to return
            
        Returns:
            List of recent run info
        """
        jobs = self.get_jobs(include_disabled=True)
        
        # Filter jobs with last_run and sort
        ran = [
            j for j in jobs 
            if j.last_run is not None
        ]
        ran.sort(key=lambda x: x.last_run, reverse=True)  # type: ignore
        
        return [
            {
                'id': j.id,
                'name': j.name,
                'last_run': j.last_run.isoformat() if j.last_run else None,
                'last_status': j.last_status,
                'duration_ms': j.last_duration_ms,
                'enabled': j.enabled
            }
            for j in ran[:count]
        ]
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Get cron jobs summary.
        
        Returns:
            Summary dict
        """
        jobs = self.get_jobs(include_disabled=True)
        
        enabled_count = sum(1 for j in jobs if j.enabled)
        
        # Count by schedule kind
        by_kind = {}
        for j in jobs:
            if j.enabled:
                by_kind[j.schedule_kind] = by_kind.get(j.schedule_kind, 0) + 1
        
        # Recent failures
        failures = [
            j for j in jobs 
            if j.last_status and j.last_status != 'ok'
        ]
        
        return {
            'total_jobs': len(jobs),
            'enabled_jobs': enabled_count,
            'disabled_jobs': len(jobs) - enabled_count,
            'by_schedule_kind': by_kind,
            'recent_failures': len(failures),
            'next_jobs': self.get_next_jobs(3)
        }
    
    def clear_cache(self):
        """Clear the cache"""
        self._cache = None
        self._cache_time = 0

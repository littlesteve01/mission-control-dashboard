"""
Stats Aggregator - Aggregates session usage data for dashboard
"""
import os
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Any, Optional
from collections import defaultdict
from dataclasses import dataclass, field
import time

from .session_parser import SessionParser, UsageEntry, SessionInfo

@dataclass
class DailyStats:
    """Aggregated stats for a single day"""
    date: str  # YYYY-MM-DD
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_cost: float = 0.0
    api_calls: int = 0  # Number of usage entries
    
    def add_entry(self, entry: UsageEntry):
        """Add a usage entry to the daily stats"""
        self.total_tokens += entry.total_tokens
        self.input_tokens += entry.input_tokens
        self.output_tokens += entry.output_tokens
        self.cache_read_tokens += entry.cache_read_tokens
        self.cache_write_tokens += entry.cache_write_tokens
        self.total_cost += entry.cost_total
        self.api_calls += 1

@dataclass
class ProviderStats:
    """Aggregated stats for a single provider/model"""
    provider: str
    model: str
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    total_cost: float = 0.0
    call_count: int = 0
    
    def add_entry(self, entry: UsageEntry):
        """Add a usage entry"""
        self.total_tokens += entry.total_tokens
        self.input_tokens += entry.input_tokens
        self.output_tokens += entry.output_tokens
        self.cache_read_tokens += entry.cache_read_tokens
        self.total_cost += entry.cost_total
        self.call_count += 1

@dataclass
class SessionStats:
    """Aggregated stats for a single session"""
    session_id: str
    started_at: datetime
    provider: str
    model: str
    total_tokens: int = 0
    total_cost: float = 0.0
    entry_count: int = 0
    last_activity: Optional[datetime] = None

class StatsAggregator:
    """
    Aggregates usage data from session parser for dashboard display.
    Implements caching to avoid re-computing stats on every request.
    """
    
    CACHE_TTL = 30  # Cache valid for 30 seconds
    
    def __init__(self, parser: Optional[SessionParser] = None):
        self.parser = parser or SessionParser()
        self._stats_cache: Dict[str, Any] = {}
        self._cache_time: Dict[str, float] = {}
    
    def _is_cache_valid(self, key: str) -> bool:
        """Check if cache entry is still valid"""
        if key not in self._cache_time:
            return False
        return (time.time() - self._cache_time[key]) < self.CACHE_TTL
    
    def _set_cache(self, key: str, value: Any):
        """Set cache entry"""
        self._stats_cache[key] = value
        self._cache_time[key] = time.time()
    
    def get_today_stats(self) -> Dict[str, Any]:
        """
        Get aggregated stats for today.
        
        Returns:
            Dict with today's stats
        """
        cache_key = "today_stats"
        if self._is_cache_valid(cache_key):
            return self._stats_cache[cache_key]
        
        today = date.today().isoformat()
        today_start = datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone.utc)
        
        stats = DailyStats(date=today)
        
        for entry in self.parser.get_usage_entries(days=1):
            # Check if entry is from today (handle timezone)
            try:
                entry_date = entry.timestamp.date().isoformat() if hasattr(entry.timestamp, 'date') else today
                # Make entry timestamp timezone-aware for comparison if needed
                entry_ts = entry.timestamp
                if entry_ts.tzinfo is None:
                    entry_ts = entry_ts.replace(tzinfo=timezone.utc)
                if entry_date == today or entry_ts >= today_start:
                    stats.add_entry(entry)
            except (AttributeError, TypeError):
                # Skip entries with invalid timestamps
                continue
        
        result = {
            'date': today,
            'tokens_total': stats.total_tokens,
            'tokens_input': stats.input_tokens,
            'tokens_output': stats.output_tokens,
            'tokens_cache_read': stats.cache_read_tokens,
            'tokens_cache_write': stats.cache_write_tokens,
            'cost_total_usd': round(stats.total_cost, 4),
            'api_calls': stats.api_calls
        }
        
        self._set_cache(cache_key, result)
        return result
    
    def get_daily_stats(self, days: Optional[int] = 7) -> List[Dict[str, Any]]:
        """
        Get daily aggregated stats for the last N days.
        
        Args:
            days: Number of days to aggregate. None = all data
            
        Returns:
            List of daily stats dicts, ordered by date
        """
        cache_key = f"daily_stats_{days}"
        if self._is_cache_valid(cache_key):
            return self._stats_cache[cache_key]
        
        daily: Dict[str, DailyStats] = {}
        
        # Initialize days (only if days is specified)
        if days is not None:
            for i in range(days):
                d = (date.today() - timedelta(days=i)).isoformat()
                daily[d] = DailyStats(date=d)
        
        # Aggregate entries
        for entry in self.parser.get_usage_entries(days=days):
            entry_date = entry.timestamp.date().isoformat() if hasattr(entry.timestamp, 'date') else None
            if entry_date:
                # For "all data" mode, dynamically create daily stats
                if days is None and entry_date not in daily:
                    daily[entry_date] = DailyStats(date=entry_date)
                if entry_date in daily:
                    daily[entry_date].add_entry(entry)
        
        # Sort by date
        result = [
            {
                'date': stats.date,
                'total_tokens': stats.total_tokens,
                'input_tokens': stats.input_tokens,
                'output_tokens': stats.output_tokens,
                'cache_read_tokens': stats.cache_read_tokens,
                'cache_write_tokens': stats.cache_write_tokens,
                'cost_usd': round(stats.total_cost, 4),
                'api_calls': stats.api_calls
            }
            for stats in sorted(daily.values(), key=lambda x: x.date)
        ]
        
        self._set_cache(cache_key, result)
        return result
    
    def get_total_stats(self) -> Dict[str, Any]:
        """
        Get total aggregated stats over all time.
        
        Returns:
            Dict with total stats
        """
        cache_key = "total_stats"
        if self._is_cache_valid(cache_key):
            return self._stats_cache[cache_key]
        
        total_tokens = 0
        total_input = 0
        total_output = 0
        total_cache_read = 0
        total_cache_write = 0
        total_cost = 0.0
        total_calls = 0
        first_date = None
        last_date = None
        
        for entry in self.parser.get_usage_entries(days=None):
            total_tokens += entry.total_tokens
            total_input += entry.input_tokens
            total_output += entry.output_tokens
            total_cache_read += entry.cache_read_tokens
            total_cache_write += entry.cache_write_tokens
            total_cost += entry.cost_total
            total_calls += 1
            
            entry_date = entry.timestamp.date() if hasattr(entry.timestamp, 'date') else None
            if entry_date:
                if first_date is None or entry_date < first_date:
                    first_date = entry_date
                if last_date is None or entry_date > last_date:
                    last_date = entry_date
        
        result = {
            'total_tokens': total_tokens,
            'input_tokens': total_input,
            'output_tokens': total_output,
            'cache_read_tokens': total_cache_read,
            'cache_write_tokens': total_cache_write,
            'cost_usd': round(total_cost, 4),
            'api_calls': total_calls,
            'first_date': first_date.isoformat() if first_date else None,
            'last_date': last_date.isoformat() if last_date else None,
            'total_days': (last_date - first_date).days + 1 if first_date and last_date else 0
        }
        
        self._set_cache(cache_key, result)
        return result
    
    def get_provider_stats(self, days: int = 7) -> List[Dict[str, Any]]:
        """
        Get stats aggregated by provider/model.
        
        Args:
            days: Number of days to aggregate
            
        Returns:
            List of provider stats
        """
        cache_key = f"provider_stats_{days}"
        if self._is_cache_valid(cache_key):
            return self._stats_cache[cache_key]
        
        providers: Dict[str, ProviderStats] = {}
        
        for entry in self.parser.get_usage_entries(days=days):
            key = f"{entry.provider}:{entry.model}"
            if key not in providers:
                providers[key] = ProviderStats(
                    provider=entry.provider,
                    model=entry.model
                )
            providers[key].add_entry(entry)
        
        result = [
            {
                'provider': stats.provider,
                'model': stats.model,
                'total_tokens': stats.total_tokens,
                'input_tokens': stats.input_tokens,
                'output_tokens': stats.output_tokens,
                'cache_read_tokens': stats.cache_read_tokens,
                'cost_usd': round(stats.total_cost, 4),
                'call_count': stats.call_count,
                'avg_tokens_per_call': stats.total_tokens // stats.call_count if stats.call_count else 0
            }
            for stats in sorted(providers.values(), key=lambda x: x.total_cost, reverse=True)
        ]
        
        self._set_cache(cache_key, result)
        return result
    
    def get_session_stats(self, days: int = 7, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Get stats for recent sessions.
        
        Args:
            days: Number of days to look back
            limit: Maximum number of sessions to return
            
        Returns:
            List of session stats
        """
        cache_key = f"session_stats_{days}_{limit}"
        if self._is_cache_valid(cache_key):
            return self._stats_cache[cache_key]
        
        sessions: Dict[str, SessionStats] = {}
        
        for cache_entry in self.parser.get_all_sessions(days=days):
            info = cache_entry.session_info
            session_stats = SessionStats(
                session_id=info.session_id,
                started_at=info.started_at,
                provider=info.provider,
                model=info.model,
                total_tokens=info.total_tokens,
                total_cost=info.total_cost,
                entry_count=info.total_entries
            )
            
            # Get last activity from entries
            if cache_entry.entries:
                session_stats.last_activity = max(e.timestamp for e in cache_entry.entries)
            
            sessions[info.session_id] = session_stats
        
        # Sort by last activity (most recent first)
        sorted_sessions = sorted(
            sessions.values(),
            key=lambda x: x.last_activity or x.started_at,
            reverse=True
        )[:limit]
        
        result = [
            {
                'session_id': s.session_id,
                'started_at': s.started_at.isoformat() if s.started_at else None,
                'last_activity': s.last_activity.isoformat() if s.last_activity else None,
                'provider': s.provider,
                'model': s.model,
                'total_tokens': s.total_tokens,
                'cost_usd': round(s.total_cost, 4),
                'entry_count': s.entry_count
            }
            for s in sorted_sessions
        ]
        
        self._set_cache(cache_key, result)
        return result
    
    def get_dashboard_stats(self) -> Dict[str, Any]:
        """
        Get all stats needed for the dashboard in one call.
        
        Returns:
            Dict with all dashboard data
        """
        today = self.get_today_stats()
        daily = self.get_daily_stats(days=7)
        providers = self.get_provider_stats(days=1)  # Today only for providers
        
        return {
            'today': today,
            'daily_history': daily,
            'providers': providers,
            'timestamp': datetime.now().isoformat()
        }
    
    def clear_cache(self):
        """Clear all caches"""
        self._stats_cache.clear()
        self._cache_time.clear()
        self.parser.clear_cache()

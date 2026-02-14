"""
Session Parser - Parses OpenClaw JSONL session files for usage data
"""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Generator
from dataclasses import dataclass, field
import hashlib
import time

@dataclass
class UsageEntry:
    """Single usage entry from a session"""
    session_id: str
    timestamp: datetime
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int = 0
    cost_total: float = 0.0
    cost_input: float = 0.0
    cost_output: float = 0.0
    cost_cache_read: float = 0.0
    cost_cache_write: float = 0.0

@dataclass
class SessionInfo:
    """Session metadata"""
    session_id: str
    started_at: datetime
    provider: str = "unknown"
    model: str = "unknown"
    cwd: str = ""
    total_entries: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0

@dataclass
class CacheEntry:
    """Cache entry for parsed session data"""
    file_path: str
    mtime: float
    size: int
    entries: List[UsageEntry]
    session_info: SessionInfo
    parsed_at: float = field(default_factory=time.time)

class SessionParser:
    """
    Parses OpenClaw session JSONL files to extract usage data.
    Implements caching to avoid re-parsing unchanged files.
    """
    
    SESSIONS_DIR = os.path.expanduser("~/.openclaw/agents/main/sessions")
    CACHE_TTL = 60  # Cache valid for 60 seconds
    
    def __init__(self, sessions_dir: Optional[str] = None):
        self.sessions_dir = Path(sessions_dir or self.SESSIONS_DIR)
        self._cache: Dict[str, CacheEntry] = {}
        self._cache_time: float = 0
    
    def _get_file_hash(self, file_path: Path) -> str:
        """Get quick hash based on mtime and size"""
        stat = file_path.stat()
        return f"{stat.st_mtime}:{stat.st_size}"
    
    def _is_cache_valid(self, file_path: Path, cache_entry: CacheEntry) -> bool:
        """Check if cache entry is still valid"""
        if not file_path.exists():
            return False
        stat = file_path.stat()
        return (stat.st_mtime == cache_entry.mtime and 
                stat.st_size == cache_entry.size)
    
    def _parse_timestamp(self, ts: str) -> Optional[datetime]:
        """Parse ISO timestamp from session file"""
        try:
            # Handle both formats: with and without milliseconds
            if '.' in ts:
                return datetime.fromisoformat(ts.replace('Z', '+00:00'))
            return datetime.fromisoformat(ts.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return None
    
    def _parse_usage(self, usage: dict) -> dict:
        """Extract usage data from usage object"""
        return {
            'input_tokens': usage.get('input', 0),
            'output_tokens': usage.get('output', 0),
            'cache_read_tokens': usage.get('cacheRead', 0),
            'cache_write_tokens': usage.get('cacheWrite', 0),
            'total_tokens': usage.get('totalTokens', 0),
            'cost': usage.get('cost', {})
        }
    
    def parse_session_file(self, file_path: Path, force: bool = False) -> Optional[CacheEntry]:
        """
        Parse a single session file, using cache if available.
        
        Args:
            file_path: Path to the JSONL file
            force: Force re-parsing even if cached
            
        Returns:
            CacheEntry with parsed data or None if file doesn't exist
        """
        if not file_path.exists():
            return None
        
        # Skip deleted files
        if '.deleted.' in file_path.name:
            return None
        
        cache_key = str(file_path)
        
        # Check cache
        if not force and cache_key in self._cache:
            if self._is_cache_valid(file_path, self._cache[cache_key]):
                return self._cache[cache_key]
        
        # Parse file
        entries: List[UsageEntry] = []
        session_info = None
        session_id = file_path.stem
        current_provider = "unknown"
        current_model = "unknown"
        
        try:
            stat = file_path.stat()
            
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip():
                        continue
                    
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    
                    entry_type = entry.get('type')
                    
                    # Session start
                    if entry_type == 'session':
                        ts = self._parse_timestamp(entry.get('timestamp', ''))
                        session_info = SessionInfo(
                            session_id=entry.get('id', session_id),
                            started_at=ts or datetime.now(),
                            cwd=entry.get('cwd', '')
                        )
                    
                    # Model change
                    elif entry_type == 'model_change':
                        current_provider = entry.get('provider', current_provider)
                        current_model = entry.get('modelId', current_model)
                    
                    # Custom model snapshot
                    elif entry_type == 'custom' and entry.get('customType') == 'model-snapshot':
                        data = entry.get('data', {})
                        current_provider = data.get('provider', current_provider)
                        current_model = data.get('modelId', current_model)
                    
                    # Message with usage
                    elif entry_type == 'message':
                        message = entry.get('message', {})
                        usage_data = message.get('usage')
                        
                        if usage_data:
                            ts = self._parse_timestamp(entry.get('timestamp', ''))
                            if not ts:
                                continue
                            
                            # Extract provider/model from message if available
                            msg_provider = message.get('provider', current_provider)
                            msg_model = message.get('model', current_model)
                            
                            # Skip delivery-mirror entries (they have 0 usage)
                            if msg_model == 'delivery-mirror':
                                continue
                            
                            usage = self._parse_usage(usage_data)
                            cost = usage['cost']
                            
                            # Only add if there's actual usage
                            if usage['total_tokens'] > 0:
                                entries.append(UsageEntry(
                                    session_id=session_id,
                                    timestamp=ts,
                                    provider=msg_provider,
                                    model=msg_model,
                                    input_tokens=usage['input_tokens'],
                                    output_tokens=usage['output_tokens'],
                                    cache_read_tokens=usage['cache_read_tokens'],
                                    cache_write_tokens=usage['cache_write_tokens'],
                                    total_tokens=usage['total_tokens'],
                                    cost_total=cost.get('total', 0.0),
                                    cost_input=cost.get('input', 0.0),
                                    cost_output=cost.get('output', 0.0),
                                    cost_cache_read=cost.get('cacheRead', 0.0),
                                    cost_cache_write=cost.get('cacheWrite', 0.0)
                                ))
            
            # Create session info if not found
            if not session_info:
                session_info = SessionInfo(
                    session_id=session_id,
                    started_at=datetime.fromtimestamp(stat.st_mtime)
                )
            
            # Update session info with aggregates
            session_info.provider = current_provider
            session_info.model = current_model
            session_info.total_entries = len(entries)
            session_info.total_tokens = sum(e.total_tokens for e in entries)
            session_info.total_cost = sum(e.cost_total for e in entries)
            
            # Cache the result
            cache_entry = CacheEntry(
                file_path=cache_key,
                mtime=stat.st_mtime,
                size=stat.st_size,
                entries=entries,
                session_info=session_info
            )
            self._cache[cache_key] = cache_entry
            
            return cache_entry
            
        except Exception as e:
            print(f"Error parsing {file_path}: {e}")
            return None
    
    def get_all_sessions(self, days: Optional[int] = 7) -> List[CacheEntry]:
        """
        Get all session data from the last N days.
        
        Args:
            days: Number of days to look back. None = all data
            
        Returns:
            List of CacheEntry objects
        """
        if not self.sessions_dir.exists():
            return []
        
        cutoff_time = None
        if days is not None:
            cutoff_time = time.time() - (days * 86400)
        
        results = []
        
        for file_path in self.sessions_dir.glob("*.jsonl"):
            # Skip old files based on mtime (only if cutoff is set)
            try:
                if cutoff_time is not None and file_path.stat().st_mtime < cutoff_time:
                    continue
            except OSError:
                continue
            
            cache_entry = self.parse_session_file(file_path)
            if cache_entry and cache_entry.entries:
                results.append(cache_entry)
        
        return results
    
    def get_usage_entries(self, days: Optional[int] = 7) -> Generator[UsageEntry, None, None]:
        """
        Generator that yields all usage entries from the last N days.
        
        Args:
            days: Number of days to look back. None = all data
            
        Yields:
            UsageEntry objects
        """
        for cache_entry in self.get_all_sessions(days):
            yield from cache_entry.entries
    
    def clear_cache(self):
        """Clear the internal cache"""
        self._cache.clear()
    
    def count_messages(self, days: int = 1) -> Dict[str, int]:
        """
        Count user and assistant messages from session files.
        Filters out system events (cron triggers, proton mail checks, etc.)
        
        Args:
            days: Number of days to look back
            
        Returns:
            Dict with 'user', 'assistant', 'system' and 'total' message counts
        """
        if not self.sessions_dir.exists():
            return {'user': 0, 'assistant': 0, 'system': 0, 'total': 0}
        
        cutoff_time = time.time() - (days * 86400)
        user_count = 0
        assistant_count = 0
        system_count = 0
        
        # Patterns that indicate system/automated messages (not real user input)
        system_patterns = [
            'System: [',           # System events
            '[cron:',              # Cron triggers
            'Proton Mail Check',   # Automated mail checks
            'XRP Kurs-Check',      # Automated price checks
            'HEARTBEAT',           # Heartbeat polls
            'Morning Briefing',    # Automated briefings
            'Exec completed',      # Exec notifications
        ]
        
        for file_path in self.sessions_dir.glob("*.jsonl"):
            try:
                if file_path.stat().st_mtime < cutoff_time:
                    continue
            except OSError:
                continue
            
            if '.deleted.' in file_path.name:
                continue
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        
                        if entry.get('type') == 'message':
                            message = entry.get('message', {})
                            role = message.get('role')
                            
                            # Skip delivery-mirror messages (session start notifications)
                            model = message.get('model', '')
                            if model == 'delivery-mirror':
                                continue
                            
                            # Check timestamp is within date range
                            ts_str = entry.get('timestamp', '')
                            if ts_str:
                                ts = self._parse_timestamp(ts_str)
                                if ts:
                                    ts_epoch = ts.timestamp()
                                    if ts_epoch < cutoff_time:
                                        continue
                            
                            if role == 'user':
                                # Check if this is a system message
                                content = message.get('content', [])
                                text = ''
                                if isinstance(content, list) and content:
                                    first_item = content[0]
                                    if isinstance(first_item, dict):
                                        text = first_item.get('text', '')
                                    elif isinstance(first_item, str):
                                        text = first_item
                                elif isinstance(content, str):
                                    text = content
                                
                                is_system = any(pattern in text for pattern in system_patterns)
                                if is_system:
                                    system_count += 1
                                else:
                                    user_count += 1
                            elif role == 'assistant':
                                assistant_count += 1
            except Exception as e:
                print(f"Error counting messages in {file_path}: {e}")
                continue
        
        return {
            'user': user_count,           # Real user messages (Telegram)
            'assistant': assistant_count,  # Bot responses
            'system': system_count,        # System/automated messages
            'total': user_count + assistant_count  # Only real conversations
        }

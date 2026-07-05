"""Data layer utilities — K-line cache expiry, multi-source failover.

ponytail: single CacheManager class covers cache expiry + failover logging.
Add distributed cache tier when multi-node deployment matters.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_KLINE_DIR = Path("data/kline_cache")


@dataclass
class CacheEntry:
    """K-line cache file metadata."""

    symbol: str
    filepath: Path
    file_size: int = 0
    data_start: str = ""
    data_end: str = ""
    rows: int = 0
    cached_at: datetime = field(default_factory=datetime.now)
    is_expired: bool = False


class CacheManager:
    """K-line cache lifecycle management — expiry, refresh, cleanup."""

    # Default TTLs
    DAILY_KLINE_TTL = timedelta(hours=6)  # Daily data: refresh every 6h
    MINUTE_KLINE_TTL = timedelta(minutes=30)  # Minute data: refresh every 30min
    TICK_KLINE_TTL = timedelta(minutes=5)  # Tick data: refresh every 5min

    def __init__(self, cache_dir: Optional[Path] = None):
        self._cache_dir = cache_dir or DEFAULT_KLINE_DIR
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def list_cache(self) -> list[CacheEntry]:
        """List all cached K-line files with metadata."""
        entries = []
        for f in sorted(self._cache_dir.glob("*.csv")):
            try:
                stat = f.stat()
                entry = CacheEntry(
                    symbol=f.stem.split("_")[0],
                    filepath=f,
                    file_size=stat.st_size,
                    cached_at=datetime.fromtimestamp(stat.st_mtime),
                )
                # Try to read date range
                import pandas as pd
                df = pd.read_csv(f, nrows=1)
                if "date" in df.columns or "日期" in df.columns:
                    date_col = "date" if "date" in df.columns else "日期"
                    entry.data_start = str(df[date_col].iloc[0])[:10]
                # Read last row for end date
                df_tail = pd.read_csv(f)
                if len(df_tail) > 0:
                    date_col = "date" if "date" in df.columns else "日期"
                    entry.data_end = str(df_tail[date_col].iloc[-1])[:10]
                    entry.rows = len(df_tail)
                entries.append(entry)
            except Exception:
                continue
        return entries

    def is_expired(self, filepath: Path, ttl: Optional[timedelta] = None) -> bool:
        """Check if a cache file has expired."""
        if not filepath.exists():
            return True
        ttl = ttl or self.DAILY_KLINE_TTL
        age = datetime.now() - datetime.fromtimestamp(filepath.stat().st_mtime)
        return age > ttl

    def cleanup_expired(self, dry_run: bool = True) -> list[str]:
        """Remove expired cache files. Returns list of removed files."""
        removed = []
        for entry in self.list_cache():
            if self.is_expired(entry.filepath):
                if not dry_run:
                    try:
                        entry.filepath.unlink()
                        removed.append(str(entry.filepath))
                    except OSError:
                        pass
                else:
                    removed.append(f"[DRY RUN] {entry.filepath}")
        logger.info("Cache cleanup: %d files %s", len(removed), "would be removed" if dry_run else "removed")
        return removed

    def get_expired_symbols(self) -> list[str]:
        """Get list of symbols whose daily cache is expired."""
        expired = []
        for entry in self.list_cache():
            if self.is_expired(entry.filepath, self.DAILY_KLINE_TTL):
                expired.append(entry.symbol)
        return expired


class FailoverTracker:
    """Multi-source failover logging and health tracking."""

    def __init__(self):
        self._failures: dict[str, list[datetime]] = {}  # source → failure timestamps
        self._successes: dict[str, list[datetime]] = {}

    def record_success(self, source: str) -> None:
        """Record a successful data fetch."""
        self._successes.setdefault(source, []).append(datetime.now())

    def record_failure(self, source: str, error: str = "") -> None:
        """Record a failed data fetch."""
        self._failures.setdefault(source, []).append(datetime.now())
        logger.warning("Data source %s failed: %s", source, error)

    def health(self, window_hours: int = 24) -> dict[str, dict]:
        """Get health status of all data sources."""
        cutoff = datetime.now() - timedelta(hours=window_hours)
        health = {}

        all_sources = set(self._successes.keys()) | set(self._failures.keys())
        for source in all_sources:
            recent_fail = sum(1 for t in self._failures.get(source, []) if t > cutoff)
            recent_ok = sum(1 for t in self._successes.get(source, []) if t > cutoff)
            total = recent_fail + recent_ok
            uptime = recent_ok / total if total > 0 else 0.0

            status = "healthy"
            if uptime < 0.5:
                status = "degraded"
            elif uptime < 0.9:
                status = "unstable"

            health[source] = {
                "status": status,
                "uptime": round(uptime, 3),
                "recent_attempts": total,
                "recent_failures": recent_fail,
            }

        return health

    def should_failover(self, source: str, max_consecutive: int = 3) -> bool:
        """Check if source should be temporarily bypassed."""
        failures = self._failures.get(source, [])
        recent = sorted(failures, reverse=True)[:max_consecutive]
        if len(recent) < max_consecutive:
            return False
        # Check if the last N failures are within a short window
        window = recent[0] - recent[-1]
        return window < timedelta(minutes=30)

    def all_degraded(self) -> list[str]:
        """List all sources currently in degraded state."""
        health = self.health(window_hours=1)
        return [s for s, h in health.items() if h["status"] == "degraded"]

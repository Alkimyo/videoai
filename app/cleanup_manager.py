import asyncio
import datetime as dt
import time
from typing import Optional, Dict, Set, List, Any
from collections import deque
import logging

logger = logging.getLogger(__name__)


class SessionCleanupManager:
    """Markaziylashtirilgan session cleanup menejeri - har bir session type uchun TTL"""
    
    # TTL konfiguratsiya (sekundda)
    CONFIG = {
        # Admin va editor sessiyalari - 1 soat (3600 sec)
        "ADMIN_ADD_SESSIONS": 3600,
        "SERIAL_RENAME_SESSIONS": 3600,
        "SERIAL_BANNER_SESSIONS": 3600,
        "LOG_QUERY_ADMINS": 3600,
        
        # Import sessiyalari - 2 soat (7200 sec)
        "IMPORT_SESSIONS": 7200,
        
        # Restore DB sessiyalari - 2 soat (7200 sec)
        "RESTORE_DB_SESSIONS": 7200,
        
        # Post sessiyalari - 1 soat (3600 sec)
        "POST_SESSIONS": 3600,
        
        # Broadcast sessiyalari - 30 minut (1800 sec)
        "BROADCAST_SESSIONS": 1800,
        "BROADCAST_TEXT_SESSIONS": 1800,
        
        # VIP sessiyalari - 30 minut (1800 sec)
        "VIP_ADD_SESSIONS": 1800,
        "VIP_PRICE_SESSIONS": 1800,
        "VIP_MESSAGE_SESSIONS": 1800,
        "VIP_CARD_SESSIONS": 1800,
        "VIP_REJECT_SESSIONS": 1800,
        "VIP_PAYMENT_SESSIONS": 1800,
        
        # User sessiyalari - 30 minut (1800 sec)
        "USER_SEARCH_SESSIONS": 1800,
        "USER_SEARCH_RESULTS": 1800,
        "USER_SERIALS_LIST": 1800,
        
        # Contact sessiyalari - 30 minut (1800 sec)
        "CONTACT_ADMIN_SESSIONS": 1800,
        "ADMIN_USER_MESSAGE_SESSIONS": 1800,
        
        # VIP Receipt - 24 soat (86400 sec)
        "VIP_RECEIPT_APPROVED": 86400,
        "VIP_RECEIPT_REJECTED": 86400,
        "VIP_RECEIPT_MESSAGES": 86400,
        "VIP_EXPIRED_NOTICE_MESSAGE_ID": 86400,
        
        # Pending start codes - 24 soat (86400 sec)
        "PENDING_START_CODES": 86400,
        
        # Upload sessiyalari - 6 soat (21600 sec)
        "SERIAL_UPLOAD_LOCKS": 21600,
        "SERIAL_UPLOAD_QUEUES": 21600,
        "SERIAL_UPLOAD_TASKS": 21600,
        "SERIAL_UPLOAD_COUNTERS": 21600,
        "SERIAL_UPLOAD_NEXT_PART": 21600,
    }
    
    def __init__(self):
        self.registered_objects = {}
        self.timestamps = {}  # (name, key) -> timestamp mappings
        self.loop_task = None
    
    def register(self, name: str, obj: Any) -> None:
        """Ob'ektni roʻyxatga ol"""
        if name not in self.CONFIG:
            logger.warning(f"Unknown session type: {name}, TTL ni qo'shish kerak")
            return
        self.registered_objects[name] = obj
        logger.debug(f"Registered session: {name} (TTL: {self.CONFIG[name]}s)")
    
    async def cleanup(self) -> None:
        """Barcha sessiyalarni tozala"""
        now = time.time()
        cleaned_count = 0
        cleaned_details = {}
        
        for name, obj in self.registered_objects.items():
            ttl = self.CONFIG.get(name, 3600)
            
            try:
                if isinstance(obj, dict):
                    cleaned = await self._cleanup_dict(obj, name, now, ttl)
                elif isinstance(obj, set):
                    cleaned = await self._cleanup_set(obj, name, now, ttl)
                else:
                    cleaned = 0
                
                cleaned_count += cleaned
                if cleaned > 0:
                    cleaned_details[name] = cleaned
            except Exception as e:
                logger.error(f"Error cleaning {name}: {e}")
        
        if cleaned_count > 0:
            logger.info(f"Cleaned {cleaned_count} expired sessions: {cleaned_details}")
    
    async def _cleanup_dict(self, session_dict: dict, name: str, 
                           now: float, ttl: int) -> int:
        """Dictionary sessiyalarni tozala"""
        cleaned = 0
        keys_to_delete = []
        
        for key, value in list(session_dict.items()):
            timestamp = None
            
            # PENDING_START_CODES: (code, part, timestamp)
            if name == "PENDING_START_CODES":
                if isinstance(value, tuple) and len(value) >= 3:
                    timestamp = value[2]
            
            # Sessiya dict'da created_at vardi
            elif isinstance(value, dict) and "created_at" in value:
                try:
                    created = dt.datetime.fromisoformat(value["created_at"])
                    timestamp = created.timestamp()
                except Exception:
                    timestamp = now - ttl - 1
            
            # VIP RECEIPT MESSAGES listni tracking
            elif isinstance(value, list):
                timestamp = self.timestamps.get((name, key), now)
            
            # Standart TTL tracking
            else:
                timestamp = self.timestamps.get((name, key), now)
            
            if timestamp and (now - timestamp) > ttl:
                keys_to_delete.append(key)
        
        for key in keys_to_delete:
            session_dict.pop(key, None)
            self.timestamps.pop((name, key), None)
            cleaned += 1
        
        return cleaned
    
    async def _cleanup_set(self, session_set: set, name: str, 
                          now: float, ttl: int) -> int:
        """Set sessiyalarni tozala"""
        cleaned = 0
        items_to_delete = []
        
        for item in session_set:
            timestamp = self.timestamps.get((name, item))
            
            if timestamp and (now - timestamp) > ttl:
                items_to_delete.append(item)
        
        for item in items_to_delete:
            session_set.discard(item)
            self.timestamps.pop((name, item), None)
            cleaned += 1
        
        return cleaned
    
    def track_session_start(self, name: str, user_id: int) -> None:
        """Session boshlanganini qayd etish"""
        self.timestamps[(name, user_id)] = time.time()
        logger.debug(f"Session started: {name}#{user_id}")
    
    def track_session_end(self, name: str, user_id: int) -> None:
        """Session tugaganini qayd etish"""
        self.timestamps.pop((name, user_id), None)
        logger.debug(f"Session ended: {name}#{user_id}")
    
    async def cleanup_loop(self) -> None:
        """Doimiy cleanup loop - har 5 minutda tekshira"""
        logger.info("Session cleanup loop started (interval: 5 min)")
        while True:
            try:
                await asyncio.sleep(300)  # 5 minutda bir cleanup
                await self.cleanup()
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
    
    def start_cleanup_loop(self) -> None:
        """Cleanup loopni boshlash"""
        if self.loop_task is None or self.loop_task.done():
            self.loop_task = asyncio.create_task(self.cleanup_loop())
            logger.info("Cleanup loop task started")
    
    async def stop_cleanup_loop(self) -> None:
        """Cleanup loopni to'xtatish"""
        if self.loop_task:
            self.loop_task.cancel()
            try:
                await self.loop_task
            except asyncio.CancelledError:
                logger.info("Cleanup loop stopped")
            self.loop_task = None
    
    def get_stats(self) -> dict:
        """Cleanup statistic"""
        stats = {
            "total_registered": len(self.registered_objects),
            "total_tracked_timestamps": len(self.timestamps),
            "configs": self.CONFIG,
            "registered_objects": {
                name: {
                    "type": type(obj).__name__,
                    "ttl": self.CONFIG.get(name, "unknown"),
                    "size": len(obj) if hasattr(obj, '__len__') else "N/A"
                }
                for name, obj in self.registered_objects.items()
            }
        }
        return stats


# Global cleanup menejeri
cleanup_manager = SessionCleanupManager()

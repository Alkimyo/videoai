import asyncio
import datetime as dt
import time
from typing import Optional, Dict, Set, List, Any
from collections import deque
import logging

logger = logging.getLogger(__name__)


class SessionCleanupManager:
    """Markaziylashtirilgan session cleanup menejeri"""
    
    # TTL konfiguratsiya (sekundda)
    CONFIG = {
        # Admin va editor sessiyalari - 1 soat
        "ADMIN_ADD_SESSIONS": 3600,
        "SERIAL_RENAME_SESSIONS": 3600,
        "SERIAL_BANNER_SESSIONS": 3600,
        "ADMIN_PERMISSION_LABELS": 3600,
        
        # Import sessiyalari - 2 soat
        "IMPORT_SESSIONS": 7200,
        
        # Restore DB sessiyalari - 2 soat
        "RESTORE_DB_SESSIONS": 7200,
        
        # Post sessiyalari - 1 soat
        "POST_SESSIONS": 3600,
        
        # Broadcast sessiyalari - 30 minut
        "BROADCAST_SESSIONS": 1800,
        "BROADCAST_TEXT_SESSIONS": 1800,
        
        # VIP sessiyalari - 30 minut
        "VIP_ADD_SESSIONS": 1800,
        "VIP_PRICE_SESSIONS": 1800,
        "VIP_MESSAGE_SESSIONS": 1800,
        "VIP_CARD_SESSIONS": 1800,
        "VIP_REJECT_SESSIONS": 1800,
        "VIP_PAYMENT_SESSIONS": 1800,
        
        # User sessiyalari - 30 minut
        "USER_SEARCH_SESSIONS": 1800,
        "USER_SEARCH_RESULTS": 1800,
        "USER_SERIALS_LIST": 1800,
        
        # Contact sessiyalari - 30 minut
        "CONTACT_ADMIN_SESSIONS": 1800,
        "CONTACT_REPLY_MAP": 3600,
        "CONTACT_REPLY_ORDER": 3600,
        
        # Log sessiyalari - 1 soat
        "LOG_QUERY_ADMINS": 3600,
        
        # Admin user message - 30 minut
        "ADMIN_USER_MESSAGE_SESSIONS": 1800,
        
        # VIP Receipt - 24 soat
        "VIP_RECEIPT_APPROVED": 86400,
        "VIP_RECEIPT_REJECTED": 86400,
        "VIP_RECEIPT_MESSAGES": 86400,
        
        # Pending start codes - 24 soat (kutish vaqti)
        "PENDING_START_CODES": 86400,
        
        # Upload sessiyalari - 6 soat
        "SERIAL_UPLOAD_LOCKS": 21600,
        "SERIAL_UPLOAD_QUEUES": 21600,
        "SERIAL_UPLOAD_TASKS": 21600,
        "SERIAL_UPLOAD_COUNTERS": 21600,
        "SERIAL_UPLOAD_NEXT_PART": 21600,
        
        # Group spam tracker - cleanup interval 10 minut
        "GROUP_SPAM_TRACKER": 600,
        
        # VIP notice - 24 soat
        "VIP_EXPIRED_NOTICE_MESSAGE_ID": 86400,
    }
    
    def __init__(self):
        self.registered_objects = {}
        self.timestamps = {}  # user_id -> timestamp mappings
        self.loop_task = None
    
    def register(self, name: str, obj: Any) -> None:
        """Ob'ektni roʻyxatga ol"""
        if name not in self.CONFIG:
            logger.warning(f"Unknown session type: {name}")
            return
        self.registered_objects[name] = obj
        logger.debug(f"Registered session: {name}")
    
    async def cleanup(self) -> None:
        """Barcha sessiyalarni tozala"""
        now = time.time()
        cleaned_count = 0
        
        for name, obj in self.registered_objects.items():
            ttl = self.CONFIG.get(name, 3600)
            
            try:
                if isinstance(obj, dict):
                    cleaned = await self._cleanup_dict(obj, name, now, ttl)
                    cleaned_count += cleaned
                elif isinstance(obj, set):
                    cleaned = await self._cleanup_set(obj, name, now, ttl)
                    cleaned_count += cleaned
                elif isinstance(obj, deque):
                    cleaned = await self._cleanup_deque(obj, name, now, ttl)
                    cleaned_count += cleaned
            except Exception as e:
                logger.error(f"Error cleaning {name}: {e}")
        
        if cleaned_count > 0:
            logger.info(f"Cleaned {cleaned_count} expired sessions")
    
    async def _cleanup_dict(self, session_dict: dict, name: str, 
                           now: float, ttl: int) -> int:
        """Dictionary sessiyalarni tozala"""
        cleaned = 0
        keys_to_delete = []
        
        for key, value in session_dict.items():
            timestamp = None
            
            # Turli session turlariga qarab timestamp topish
            if name == "ADMIN_ADD_SESSIONS":
                timestamp = self.timestamps.get((name, key))
            elif name == "PENDING_START_CODES":
                # Format: (code, part, timestamp)
                if isinstance(value, tuple) and len(value) >= 3:
                    timestamp = value[2]
            elif name == "CONTACT_REPLY_MAP":
                # Contact reply sessiyasi - maxfiy adr
                continue  # Kontrollangan qo'shish/olib tashlash
            elif name == "VIP_RECEIPT_MESSAGES":
                timestamp = self.timestamps.get((name, key))
            elif isinstance(value, dict) and "created_at" in value:
                # Sessiya dict'da created_at vardi
                try:
                    created = dt.datetime.fromisoformat(value["created_at"])
                    timestamp = created.timestamp()
                except:
                    timestamp = now - ttl - 1
            elif isinstance(value, dict) and "timestamp" in value:
                timestamp = value.get("timestamp")
            else:
                # Standart TTL
                timestamp = self.timestamps.get((name, key), now - ttl - 1)
            
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
    
    async def _cleanup_deque(self, session_deque: deque, name: str, 
                           now: float, ttl: int) -> int:
        """Deque sessiyalarni tozala"""
        cleaned = 0
        
        if name == "CONTACT_REPLY_ORDER":
            # Deque automatik maxlen ga qarab truncate qiladi
            # Qo'shimcha cleanup kerak emas
            return 0
        
        # Boshqa deque tiplari uchun
        return cleaned
    
    def track_session_start(self, name: str, user_id: int) -> None:
        """Session boshlanganini qayd etish"""
        self.timestamps[(name, user_id)] = time.time()
    
    def track_session_end(self, name: str, user_id: int) -> None:
        """Session tugaganini qayd etish"""
        self.timestamps.pop((name, user_id), None)
    
    async def cleanup_loop(self) -> None:
        """Doimiy cleanup loop"""
        logger.info("Session cleanup loop started")
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
    
    async def stop_cleanup_loop(self) -> None:
        """Cleanup loopni to'xtatish"""
        if self.loop_task:
            self.loop_task.cancel()
            try:
                await self.loop_task
            except asyncio.CancelledError:
                pass
            self.loop_task = None


# Global cleanup menejeri
cleanup_manager = SessionCleanupManager()

import asyncio
import time
from typing import Dict, Optional


class UserSessionManager:
    def __init__(self, logger):
        self.user_sessions: Dict[str, dict] = {}
        self.active_tasks: Dict[str, set] = {}
        self.logger = logger

    def create_user_session(self, user_id: str, sid: str, endpoint: Optional[str] = None):
        self.user_sessions[user_id] = {
            'sid': sid,
            'current_mode': 'friend',
            'chat_history': {},
            'active_tts_task': None,
            'is_speaking': False,
            'current_audio': None,
            'created_at': time.time(),
            'endpoint': endpoint or "default"
        }
        self.active_tasks[user_id] = set()
        self.logger.info(f"Created session for {user_id} with endpoint: {self.user_sessions[user_id]['endpoint']}")

    def set_user_endpoint(self, user_id: str, endpoint: str):
        session = self.get_user_session(user_id)
        if session:
            session["endpoint"] = endpoint
            self.logger.info(f"Updated endpoint for {user_id} to {endpoint}")

    def get_user_endpoint(self, user_id: str) -> Optional[str]:
        session = self.get_user_session(user_id)
        return session.get("endpoint") if session else None

    def get_user_session(self, user_id: str):
        return self.user_sessions.get(user_id)

    def cleanup_user_session(self, user_id: str):
        if user_id in self.user_sessions:
            if user_id in self.active_tasks:
                for task in self.active_tasks[user_id]:
                    if not task.done():
                        task.cancel()
                del self.active_tasks[user_id]
            del self.user_sessions[user_id]
            self.logger.info(f"Cleaned up session for user: {user_id}")

    def add_task(self, user_id: str, task: asyncio.Task):
        if user_id not in self.active_tasks:
            self.active_tasks[user_id] = set()
        self.active_tasks[user_id].add(task)
        task.add_done_callback(lambda t: self.remove_task(user_id, t))

    def remove_task(self, user_id: str, task: asyncio.Task):
        if user_id in self.active_tasks and task in self.active_tasks[user_id]:
            self.active_tasks[user_id].remove(task)
            self.logger.info(f"Removed task for user {user_id}: {task.get_name() if hasattr(task, 'get_name') else task}")

    def cancel_user_tasks(self, user_id: str):
        if user_id in self.active_tasks:
            for task in list(self.active_tasks[user_id]):
                if not task.done():
                    task.cancel()
                    self.logger.info(f"Cancelled task for user {user_id}: {task.get_name() if hasattr(task, 'get_name') else task}")
            self.active_tasks[user_id].clear()

    def stop_current_tts(self, user_id: str):
        if user_id in self.user_sessions:
            self.user_sessions[user_id]['is_speaking'] = False
            self.user_sessions[user_id]['current_audio'] = None
            self.logger.info(f"Stopped TTS for user: {user_id}")


    def get_all_sids(self):
        return [
            session["sid"]
            for session in self.user_sessions.values()
            if "sid" in session
        ]
        
    def clear_all_sessions(self):
        # Cancel all running tasks
        for user_id in list(self.active_tasks.keys()):
            self.cancel_user_tasks(user_id)
    
        # Clear all sessions
        self.user_sessions.clear()
        self.active_tasks.clear()
        self.logger.info("✅ Cleared all user sessions and active tasks.")
import tiktoken
from typing import Dict, Any, Optional, Union, List
from uuid import uuid4
from threading import Lock
from datetime import datetime, timedelta, date
from config import Config
import threading
import atexit
import logging
from collections import defaultdict
from typing import DefaultDict 
from pathlib import Path  
from apscheduler.schedulers.background import BackgroundScheduler
import csv
import os, json
import shutil
from sqlalchemy.orm import Session
from sqlalchemy import func
from .subscription import Subscription
from inai_project.database import get_db
from enum import Enum
from dataclasses import dataclass
from apscheduler.schedulers.base import STATE_RUNNING  # add this import
scheduler = BackgroundScheduler()  # single global instance



config = Config()
CSV_PATH = Path(__file__).parent / "DataMonitor" / "token_usage.csv"
BACKUP_DIR = Path(__file__).parent / "DataMonitor" / "backups"
last_csv_rotation_time = None
logging.getLogger("apscheduler").setLevel(logging.WARNING)
# Create backup directory if it doesn't exist
BACKUP_DIR.mkdir(exist_ok=True, parents=True)

EXHAUSTED_USERS_FILE = Path(__file__).parent / "DataMonitor" / "exhausted_users.json"
EXHAUSTED_USERS_FILE.parent.mkdir(exist_ok=True, parents=True)
api_keys = config.api_keys
if not api_keys:
    raise ValueError("❌ No API keys found in GROQ_API_KEY")

user_sessions: Dict[str, Dict] = {}
key_usage_count: Dict[str, int] = {key: 0 for key in api_keys}
lock = Lock()
# user_token_usage: Dict[str, Dict[str, object]] = {}  
# api_key_token_usage: Dict[str, Dict[str, object]] = {}
user_token_usage: Dict[str, Dict[str, Any]] = {}
api_key_token_usage: Dict[str, Dict[str, Any]] = {}
exhausted_users: Dict[str, Dict] = {}
token_usage_per_user = {}
DEFAULT_DAILY_TOKEN_LIMIT = 250000  # Updated from 250000


print(f"🔐 Loaded {len(api_keys)} API keys")
for i, key in enumerate(api_keys):
    print(f"[{i+1:02d}] {key[:10]}...")
    
def _is_subscription_active(subscription) -> bool:
    """Return True if subscription is active (handles date/datetime/None safely)."""

    if subscription is None:
        return False

    end = subscription.end_date
    if end is None:
        return True
    # now handle both date and datetime types
    now_dt = datetime.utcnow()
    if isinstance(end, datetime):
        return end > now_dt
    if isinstance(end, date):
        return end >= now_dt.date()
    # unknown type -> treat as inactive
    return False

def get_user_token_limit(user_id: str, db: Session = None) -> int:
    """
    Get token limit for a user based on their subscription.
    Returns subscription max_token if active, otherwise default limit.
    """

    created_db = False
    if db is None:
        db = next(get_db())
        created_db = True
    
    try:
        # Convert string user_id to int if needed
        try:
            numeric_user_id = int(user_id.replace("user", ""))
        except (ValueError, AttributeError):
            # If conversion fails, use default limit
            print(f"⚠ Invalid user ID format: {user_id}, using default limit")
            return DEFAULT_DAILY_TOKEN_LIMIT
        
        # Query for active subscription
        subscription = db.query(Subscription).filter(
            Subscription.user_id == numeric_user_id,
            Subscription.status == "active"
        ).first()
        
        if subscription and _is_subscription_active(subscription):
            # If max_token is None -> unlimited
            if subscription.max_token is None:
                print(f"♾️ User {user_id} has unlimited subscription: {subscription.plan_name}")
                return None
            # Ensure it's an int
            if subscription.max_token is not None:
                try:
                    return int(subscription.max_token)
                except Exception:
                    return DEFAULT_DAILY_TOKEN_LIMIT
                    
        return DEFAULT_DAILY_TOKEN_LIMIT

    except Exception as e:
        print(f"❌ Error fetching subscription for {user_id}: {e}")
        return DEFAULT_DAILY_TOKEN_LIMIT
    finally:
        if created_db:
            db.close()
            
def get_user_subscription_info(user_id: str, db: Session = None) -> Optional[Dict]:
    """Get detailed subscription information for a user"""
    created_db = False
    if db is None:
        db = next(get_db())
        created_db = True
    
    try:
        # Convert string user_id to int if needed
        try:
            numeric_user_id = int(user_id.replace("user", ""))
        except (ValueError, AttributeError):
            # If conversion fails, use a default value or handle accordingly
            print(f"⚠ Invalid user ID format: {user_id}")
            return None
        
        subscription = db.query(Subscription).filter(
            Subscription.user_id == numeric_user_id,
            func.lower(Subscription.status) == "active"
        ).first()
        
        if subscription:
            return {
                "sub_id": subscription.sub_id,
                "plan_name": subscription.plan_name,
                "max_token": subscription.max_token,
                "start_date": subscription.start_date,
                "end_date": subscription.end_date,
                "is_active": _is_subscription_active(subscription)
            }
        
        return None
        
    except Exception as e:
        print(f"❌ Error fetching subscription info for {user_id}: {e}")
        return None
    finally:
        if created_db:
            db.close()
            
def load_exhausted_users() -> Dict[str, Dict]:
    if EXHAUSTED_USERS_FILE.exists():
        try:
            with open(EXHAUSTED_USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def save_exhausted_users():
    with open(EXHAUSTED_USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(exhausted_users, f, indent=2, default=str)  # default=str for dates


# Load on startup

exhausted_users.update(load_exhausted_users())
print(f":closed_lock_with_key: Loaded {len(api_keys)} API keys")
for i, key in enumerate(api_keys):
    print(f"[{i+1:02d}] {key[:10]}...")
        
def count_tokens(text: str, api_key: str) -> int:
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
        encoded = encoding.encode(text)
        return len(encoded)
    except Exception as e:
        # print(f"⚠ Token encoding failed: {e}")
        print(f":warning: Token encoding failed for API key {api_key}: {e}")
        return 0

def create_new_csv():
    """Create a new CSV file with headers"""
    CSV_PATH.parent.mkdir(exist_ok=True, parents=True)
    
    with open(CSV_PATH, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=[
            "Timestamp", "User ID", "API Key", "Question Tokens", "Answer Tokens",
            "Total Tokens", "API Key Total Tokens Used", "Task", "Token Limit", 
            "Plan Name", "Source"
        ])
        writer.writeheader()
    print("🆕 New CSV file created with subscription and source tracking")
    
def restore_if_upgraded(user_id: str, db: Session = None) -> None:
    """Restore user access if their subscription was upgraded"""
    if user_id in exhausted_users:
        current_limit = get_user_token_limit(user_id, db)
        if current_limit is None or current_limit > DEFAULT_DAILY_TOKEN_LIMIT:
            exhausted_users.pop(user_id, None)
            save_exhausted_users()

def check_user_limit(user_id: str, new_tokens: int, db: Session = None) -> bool:
    with lock:
        restore_if_upgraded(user_id, db)
        user_limit = get_user_token_limit(user_id, db)

        if user_limit is None:  # Unlimited plan
            return True

        total_usage = get_total_token_usage(user_id)
        current_tokens = total_usage.total_tokens
        would_exceed = (current_tokens + new_tokens) > user_limit

        if would_exceed:
            subscription_info = get_user_subscription_info(user_id, db)
            plan_info = f" ({subscription_info['plan_name']})" if subscription_info else " (Free)"
            print(f"🚫 User {user_id} would exceed limit: {current_tokens + new_tokens}/{user_limit}{plan_info}")
            # NEW: record exhausted immediately so the monitor sees it
            move_to_exhausted(user_id)

        return not would_exceed


def add_tokens(user_id: str, api_key: str, question_tokens: int, answer_tokens: int):
    total = question_tokens + answer_tokens

    reset_user_tokens_if_new_day(user_id)
    reset_api_key_tokens_if_new_day(api_key)

    if not check_user_limit(user_id, total):
        # Ensure exhausted state persists and shows up
        move_to_exhausted(user_id)
        return False

    update_user_tokens(user_id, total)
    update_api_key_tokens(api_key, total)

    update_csv_log(
        CSV_PATH,
        user_id=user_id,
        api_key=api_key,
        question_tokens=question_tokens,
        answer_tokens=answer_tokens,
        total_tokens=get_user_tokens(user_id),
        api_key_token_total=get_api_key_tokens(api_key),
        task="Token Update"
    )
    logging.info(f"[TOKENS] {user_id} now has {get_user_tokens(user_id)} tokens used.")
    return True

def get_usage_logs() -> dict:
    latest_by_api_key = {}
    latest_by_user = {}

    if not os.path.exists(CSV_PATH):
        return {"api_keys": {}, "user_ids": {}}

    with open(CSV_PATH, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            try:
                api_key = row["API Key"]
                user_id = row["User ID"]
                total_tokens = int(row["Total Tokens"])
                api_key_token_used = int(row["API Key Total Tokens Used"])

                # Latest by API key - keep max token used record
                if api_key not in latest_by_api_key or api_key_token_used > int(latest_by_api_key[api_key]["API Key Total Tokens Used"]):
                    latest_by_api_key[api_key] = row

                # Latest by user - keep max token used record
                if user_id not in latest_by_user or total_tokens > int(latest_by_user[user_id]["Total Tokens"]):
                    latest_by_user[user_id] = row
            except (ValueError, KeyError):
                continue

    return {
        "api_keys": latest_by_api_key,
        "user_ids": latest_by_user
    }

def load_token_usage_from_csv():
    """Load both user and API key token usage from CSV on startup"""
    global user_token_usage, api_key_token_usage
    
    if not CSV_PATH.exists():
        print("📝 CSV file doesn't exist, starting with fresh counters")
        for key in api_keys:
            api_key_token_usage[key] = {
                "tokens": 0,
                "date": datetime.now().strftime("%Y-%m-%d")
            }
        return
        
    try:
        logs = get_usage_logs()
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        # Load user token usage (existing code)
        for user_id, row in logs["user_ids"].items():
            user_token_usage[user_id] = {
                "date": today_str,
                "tokens": int(row.get("Total Tokens", 0)),
            }
            # print(f"👤 Loaded user {user_id} with {user_token_usage[user_id]['tokens']} tokens")
        
        # 🔹 NEW: Load API key token usage
        for api_key, row in logs["api_keys"].items():
            try:
                api_key_total_tokens = int(row.get("API Key Total Tokens Used", 0))
                api_key_token_usage[api_key] = {
                    "tokens": api_key_total_tokens,
                    "date": today_str
                }
                print(f"📊 Loaded API key {api_key[:10]}... with {api_key_total_tokens} tokens")
            except (ValueError, KeyError) as e:
                print(f"⚠️ Error loading tokens for API key {api_key[:10]}...: {e}")
                api_key_token_usage[api_key] = {
                    "tokens": 0,
                    "date": today_str
                    
                }
        
        # Ensure all API keys have entries (in case some weren't in CSV)
        for key in api_keys:
            if key not in api_key_token_usage:
                api_key_token_usage[key] = {
                    "tokens": 0,
                    "date": today_str
                }
                print(f"🆕 New API key {key[:10]}... initialized with 0 tokens")
                
        print(f"✅ Loaded token usage for {len(user_token_usage)} users and {len(api_key_token_usage)} API keys")
        
    except Exception as e:
        print(f"❌ Error loading token usage from CSV: {e}")
        # Initialize with zeros if loading fails
        for key in api_keys:
            api_key_token_usage[key] = {
                "tokens": 0,
                "date": datetime.now().strftime("%Y-%m-%d")
            }


def get_user_tokens(user_id: str) -> int:
    with lock:
        data = user_token_usage.get(user_id)
        if not data:
            return 0
        tokens = data.get("tokens", 0)
        if not isinstance(tokens, int):
            print(f"⚠ Invalid token data for user {user_id}: {data}")
            return 0
        return tokens
    
def get_api_key_tokens(api_key: str) -> int:
    with lock:
        data = api_key_token_usage.get(api_key)
        if not data:
            return 0
        tokens = data.get("tokens", 0)
        if not isinstance(tokens, int):
            print(f"⚠ Invalid token data for API key {api_key}: {data}")
            return 0
        return tokens


def reset_user_tokens_if_new_day(user_id: str):
    today_str = datetime.now().strftime("%Y-%m-%d")
    with lock:
        data = user_token_usage.get(user_id)
        if not data or data.get("date") != today_str:
            user_token_usage[user_id] = {"tokens": 0, "date": today_str}

def reset_api_key_tokens_if_new_day(api_key: str):
    today_str = datetime.now().strftime("%Y-%m-%d")
    with lock:
        data = api_key_token_usage.get(api_key)
        if not data or data.get("date") != today_str:
            api_key_token_usage[api_key] = {"tokens": 0, "date": today_str}

def update_user_tokens(user_id: str, additional_tokens: int):
    today_str = datetime.now().strftime("%Y-%m-%d")
    with lock:
        if user_id not in user_token_usage or user_token_usage[user_id]["date"] != today_str:
            user_token_usage[user_id] = {"tokens": 0, "date": today_str}
        if not isinstance(user_token_usage[user_id].get("tokens"), int):
            user_token_usage[user_id]["tokens"] = 0
        user_token_usage[user_id]["tokens"] += additional_tokens

def update_api_key_tokens(api_key: str, additional_tokens: int):
    today_str = datetime.now().strftime("%Y-%m-%d")
    with lock:
        if api_key not in api_key_token_usage or api_key_token_usage[api_key]["date"] != today_str:
            api_key_token_usage[api_key] = {"tokens": 0, "date": today_str}
        if not isinstance(api_key_token_usage[api_key].get("tokens"), int):
            api_key_token_usage[api_key]["tokens"] = 0
        api_key_token_usage[api_key]["tokens"] += additional_tokens

def clear_memory_counters():
    """Clear in-memory counters after rotation"""
    global user_token_usage
    with lock:
        user_token_usage.clear()
    print("🔄 Memory counters cleared")

def reset_all_counters():
    """Complete reset - use this only for fresh start"""
    global user_token_usage, api_key_token_usage
    today_str = datetime.now().strftime("%Y-%m-%d")
    with lock:
        user_token_usage.clear()
        for key in api_keys:
            api_key_token_usage[key] = {
                "tokens": 0,
                "date": today_str
            }
        print("🔄 All counters completely reset to zero")

def rotate_csv_file():
    """Rotate CSV file with timestamp backup"""
    global last_csv_rotation_time

    if not CSV_PATH.exists():
        create_new_csv()
        last_csv_rotation_time = datetime.now()
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"token_usage_{timestamp}.csv"
    backup_path = BACKUP_DIR / backup_filename

    try:
        shutil.copy2(CSV_PATH, backup_path)
        print(f"📁 CSV backed up: {backup_path}")

        create_new_csv()
        clear_memory_counters()
        load_token_usage_from_csv() 

        # ✅ Update rotation time
        last_csv_rotation_time = datetime.now()

    except Exception as e:
        print(f"❌ Error rotating CSV: {e}")

# Add these new types
class TokenSource(Enum):
    GROQ = "groq"
    TAVILY = "tavily" 
    COHERE = "cohere"
    ASSISTANT = "assistant"
    COMBINED = "combined"

@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    source: TokenSource

# Add new tracking dictionaries while keeping existing ones
token_usage_by_source: Dict[str, Dict[TokenSource, TokenUsage]] = {}
token_usage_per_user = defaultdict(lambda: {"tokens": 0, "date": datetime.now().strftime("%Y-%m-%d")})

def update_csv_log(CSV_PATH, user_id, api_key, question_tokens, answer_tokens, 
                  total_tokens, api_key_token_total, task, token_limit=None, 
                  plan_name="Free", source: TokenSource = TokenSource.GROQ):
    """Update CSV log with enhanced source tracking"""
    
    if isinstance(CSV_PATH, str):
        CSV_PATH = Path(CSV_PATH)

    if not CSV_PATH.exists():
        create_new_csv()

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    fieldnames = [
        "Timestamp", "User ID", "API Key", "Question Tokens", "Answer Tokens",
        "Total Tokens", "API Key Total Tokens Used", "Task", "Token Limit", 
        "Plan Name", "Source"
    ]

    rows = []
    if os.path.isfile(CSV_PATH):
        with open(CSV_PATH, mode="r", newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            rows = list(reader)

    # Update existing or add new row
    updated = False
    for row in rows:
        if (row["User ID"] == str(user_id) and 
            row.get("Source", TokenSource.GROQ.value) == source.value):
            row.update({
                "Question Tokens": str(question_tokens),
                "Answer Tokens": str(answer_tokens),
                "Total Tokens": str(total_tokens),
                "API Key Total Tokens Used": str(api_key_token_total),
                "Timestamp": now_str,
                "API Key": api_key,
                "Task": task,
                "Token Limit": str(token_limit or DEFAULT_DAILY_TOKEN_LIMIT),
                "Plan Name": plan_name,
                "Source": source.value
            })
            updated = True
            break

    if not updated:
        rows.append({
            "Timestamp": now_str,
            "User ID": str(user_id),
            "API Key": api_key,
            "Question Tokens": str(question_tokens),
            "Answer Tokens": str(answer_tokens),
            "Total Tokens": str(total_tokens),
            "API Key Total Tokens Used": str(api_key_token_total),
            "Task": task,
            "Token Limit": str(token_limit or DEFAULT_DAILY_TOKEN_LIMIT),
            "Plan Name": plan_name,
            "Source": source.value
        })

    # Write updated CSV
    with open(CSV_PATH, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

def assign_key_to_user(user_id: str, task: str = "Unknown Task") -> Dict:
    with lock:
        if user_id in user_sessions:
            return {
                "api_key": user_sessions[user_id]["api_key"],
                "message": "Already assigned"
            }

        min_usage = min(key_usage_count.values())
        candidates = [key for key, count in key_usage_count.items() if count == min_usage]
        key = candidates[0]  

        key_usage_count[key] += 1
        session_id = str(uuid4())
        user_sessions[user_id] = {
            "session_id": session_id,
            "api_key": key,
            "start_time": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            "task": task,
            "last_active": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            "sid": None
        }

        return {
            "api_key": key,
            "message": f"✅ Assigned least-loaded key {api_keys.index(key)+1} to {user_id}"
        }

def update_last_active(user_id: str, sid: str = None):
    with lock:
        if user_id in user_sessions:
            user_sessions[user_id]["last_active"] = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            if sid:
                user_sessions[user_id]["sid"] = sid

def release_key_for_user(user_id: str) -> Dict:
    with lock:
        session = user_sessions.pop(user_id, None)
        if session:
            key = session["api_key"]
            if key in key_usage_count:
                key_usage_count[key] = max(0, key_usage_count[key] - 1)
            return {"message": f"✅ Released key for {user_id}"}
        return {"error": "⚠ User session not found or already released"}
    
def move_to_exhausted(user_id: str):
    """Move user to exhausted state when they exceed their token limit"""
    with lock:
        # If already exhausted, update tokens/timestamp instead of returning silently
        usage = user_token_usage.get(user_id, {"tokens": 0})
        token_count = usage.get("tokens", 0) if isinstance(usage, dict) else usage

        session = user_sessions.pop(user_id, None)

        exhausted_entry = {
            "user_id": user_id,  # <-- IMPORTANT: include user_id in the saved object
            "exhausted_at": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            "tokens": token_count,
        }

        if session:
            exhausted_entry.update({
                "session_id": session.get("session_id"),
                "api_key": session.get("api_key"),
                "task": session.get("task"),
                "last_active": session.get("last_active"),
                "sid": session.get("sid"),
            })
            # Release API key usage count
            key = session.get("api_key")
            if key in key_usage_count:
                key_usage_count[key] = max(0, key_usage_count[key] - 1)

        exhausted_users[user_id] = exhausted_entry
        save_exhausted_users()
        print(f"🚫 User {user_id} moved to exhausted state with {token_count} tokens")



def reset_counters():
    global token_usage_per_user, api_key_token_usage, exhausted_users
    token_usage_per_user.clear()
    today_str = datetime.now().strftime("%Y-%m-%d")
    for key in api_keys:
        api_key_token_usage[key] = {
            "tokens": 0,
            "date": today_str
        }
    exhausted_users.clear()
    print("[RESET] Counters and exhausted users have been reset.")

def get_monitor_data() -> Dict:
    with lock:
        return {
            "total_keys": len(api_keys),
            "key_usage": key_usage_count,
            "user_sessions": {
                user_id: {**session, "user_id": user_id}
                for user_id, session in user_sessions.items()
            },
            "token_usage_per_user": dict(sorted(
                ((user_id, usage["tokens"] if isinstance(usage, dict) else usage)
                 for user_id, usage in user_token_usage.items()),
                key=lambda x: x[1],
                reverse=True
            )),
            "api_key_token_usage": {
                key: (data["tokens"] if isinstance(data, dict) else data)
                for key, data in api_key_token_usage.items()
            },
            # NEW: full exhausted map for detail pages
            "exhausted_users": exhausted_users,
            # If your UI expects a simple list, this keeps backward-compat:
            "exhausted_summary": [
                {
                    "user_id": uid,
                    "token_usage": (info.get("tokens", 0)
                                    if isinstance(info.get("tokens"), int)
                                    else info.get("tokens", 0))
                }
                for uid, info in exhausted_users.items()
            ],
        }


def save_token_usage_to_csv():
    print("💾 Token usage saved to CSV")

# 🔹 Delayed job setup
def delayed_job_setup():
    atexit.register(save_token_usage_to_csv)

    # avoid duplicate interval job if this runs more than once
    if not any(j.id == "save_token_usage" for j in scheduler.get_jobs()):
        scheduler.add_job(
            save_token_usage_to_csv,
            "interval",
            minutes=1,
            id="save_token_usage"
        )

    # start the scheduler once
    if scheduler.state != STATE_RUNNING:
        scheduler.start()


# ✅ Run after Python finishes loading everything
threading.Timer(0.1, delayed_job_setup).start()
        
def clear_monitor_counts_only():
    with lock:
        # Restore exhausted users back to active sessions
        # for user_id, data in exhausted_users.items():
        #     user_sessions[user_id] = {
        #         "session_id": data["session_id"],
        #         "api_key": data["api_key"],
        #         "start_time": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
        #         "task": data["task"],
        #         "last_active": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
        #         "sid": None
        #     }
        #     key_usage_count[data["api_key"]] = key_usage_count.get(data["api_key"], 0) + 1
        
        # exhausted_users.clear()
        user_token_usage.clear()
        today_str = datetime.now().strftime("%Y-%m-%d")
        for key in api_keys:
            api_key_token_usage[key] = {
                "tokens": 0,
                "date": today_str
            }

    print("✅ Counters cleared, exhausted users restored to active.")

def reset_and_rotate():
    """Clear counters and create a fresh CSV daily"""
    clear_monitor_counts_only()
    rotate_csv_file()
    print("✅ Daily reset + CSV rotation done")
            
def schedule_daily_reset():
    # use the same global scheduler; do NOT re-create a new one
    if not any(j.id == "daily_reset" for j in scheduler.get_jobs()):
        scheduler.add_job(
            lambda: (clear_monitor_counts_only(), rotate_csv_file(), print("✅ Daily reset + CSV rotation done")),
            'cron',
            hour=18,
            minute=30,
            id="daily_reset"
        )
    print("⏳ Daily reset scheduled for 12:00 AM.")


print("🔄 Loading existing token usage from CSV...")
load_token_usage_from_csv()
print("✅ Startup loading complete!")

# Add these new imports at the top
from typing import Dict, Any, Optional, Union, List
from dataclasses import dataclass
from enum import Enum

# Add these new types after the existing imports
class TokenSource(Enum):
    GROQ = "groq"
    TAVILY = "tavily" 
    COHERE = "cohere"
    ASSISTANT = "assistant"
    COMBINED = "combined"

@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    source: TokenSource

# Add new tracking dictionaries while keeping existing ones
token_usage_by_source: Dict[str, Dict[TokenSource, TokenUsage]] = {}
token_usage_per_user = defaultdict(lambda: {"tokens": 0, "date": datetime.now().strftime("%Y-%m-%d")})

def track_token_usage(
    user_id: str,
    input_tokens: int, 
    output_tokens: int,
    source: TokenSource,
    api_key: Optional[str] = None
) -> TokenUsage:
    """Track token usage from different sources"""
    if user_id not in token_usage_by_source:
        token_usage_by_source[user_id] = {}
    
    total_tokens = input_tokens + output_tokens
    usage = TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        source=source
    )
    
    token_usage_by_source[user_id][source] = usage

    # Update existing token tracking system
    if source in [TokenSource.GROQ, TokenSource.ASSISTANT]:
        if api_key:
            add_tokens(user_id, api_key, input_tokens, output_tokens)
    
    return usage

def get_total_token_usage(user_id: str) -> TokenUsage:
    """Get combined token usage across all sources"""
    if user_id not in token_usage_by_source:
        return TokenUsage(0, 0, 0, TokenSource.COMBINED)
    
    total_input = 0
    total_output = 0
    
    for usage in token_usage_by_source[user_id].values():
        total_input += usage.input_tokens
        total_output += usage.output_tokens
    
    return TokenUsage(
        input_tokens=total_input,
        output_tokens=total_output,
        total_tokens=total_input + total_output,
        source=TokenSource.COMBINED
    )



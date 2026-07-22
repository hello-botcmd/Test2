"""
account_load.py - Account loading and management for the Telegram Account Manager.
Handles adding accounts via Phone+OTP+2FA, Session String File, and TData.
"""
import os
import re
import zipfile
import tempfile
import asyncio
import logging
from typing import Optional, Tuple, List
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    FloodWaitError,
    PhoneNumberInvalidError,
    PhoneNumberBannedError,
)
from telethon.tl.functions.account import UpdateProfileRequest
import config
from database import db

logger = logging.getLogger(__name__)


async def create_telethon_client(session_string: Optional[str] = None) -> TelegramClient:
    """Create a Telethon client with optional existing session string."""
    if session_string:
        client = TelegramClient(StringSession(session_string), config.API_ID, config.API_HASH)
    else:
        client = TelegramClient(StringSession(), config.API_ID, config.API_HASH)
    return client


async def connect_and_check(client: TelegramClient) -> bool:
    """Connect and check if user is authorized."""
    try:
        await client.connect()
        return await client.is_user_authorized()
    except Exception as e:
        logger.error(f"Connection error: {e}")
        return False


async def send_otp(phone: str) -> Tuple[bool, str, TelegramClient]:
    """
    Send OTP to phone number.
    Returns (success, message, client).
    """
    client = await create_telethon_client()
    try:
        await client.connect()
        await client.send_code_request(phone)
        return True, "OTP sent successfully. Please enter the code.", client
    except FloodWaitError as e:
        await client.disconnect()
        return False, f"⚠️ Flood wait: please wait {e.seconds} seconds before trying again.", None
    except PhoneNumberInvalidError:
        await client.disconnect()
        return False, "❌ Invalid phone number format. Use international format (e.g., +1234567890).", None
    except PhoneNumberBannedError:
        await client.disconnect()
        return False, "❌ This phone number is banned from Telegram.", None
    except Exception as e:
        await client.disconnect()
        return False, f"❌ Failed to send OTP: {str(e)}", None


async def verify_otp(client: TelegramClient, phone: str, code: str, password: Optional[str] = None) -> Tuple[bool, str]:
    """
    Verify OTP and optionally complete 2FA.
    Returns (success, message_or_session_string).
    """
    try:
        await client.sign_in(phone, code)
        session_str = client.session.save()
        return True, session_str
    except SessionPasswordNeededError:
        if password:
            try:
                await client.sign_in(password=password)
                session_str = client.session.save()
                return True, session_str
            except Exception as e:
                return False, f"❌ 2FA failed: {str(e)}"
        else:
            return False, "2FA_REQUIRED"
    except PhoneCodeInvalidError:
        return False, "❌ Invalid OTP code. Please check and try again."
    except PhoneCodeExpiredError:
        return False, "❌ OTP code has expired. Please request a new one."
    except Exception as e:
        return False, f"❌ Sign in failed: {str(e)}"


async def verify_2fa(client: TelegramClient, password: str) -> Tuple[bool, str]:
    """Complete 2FA verification."""
    try:
        await client.sign_in(password=password)
        session_str = client.session.save()
        return True, session_str
    except Exception as e:
        return False, f"❌ 2FA failed: {str(e)}"


async def update_account_name(client: TelegramClient) -> bool:
    """Update the account's profile name from the name.txt file."""
    try:
        name = get_random_name()
        parts = name.split(" ", 1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else ""
        await client(UpdateProfileRequest(
            first_name=first_name,
            last_name=last_name
        ))
        return True
    except Exception as e:
        logger.warning(f"Failed to update profile name: {e}")
        return False


def get_random_name() -> str:
    """Get a random name from the name.txt file."""
    try:
        with open(config.NAME_FILE, "r", encoding="utf-8") as f:
            names = [line.strip() for line in f if line.strip()]
        if names:
            import random
            return random.choice(names)
    except FileNotFoundError:
        logger.warning(f"{config.NAME_FILE} not found, using default names.")
    except Exception as e:
        logger.warning(f"Error reading name file: {e}")
    
    # Fallback names
    import random
    fallbacks = [
        "Alex Morgan", "Jordan Riley", "Casey Taylor", "Avery Quinn",
        "Drew Parker", "Hayden Blake", "Logan Reese", "Dakota Skyler",
        "Cameron Harper", "Rowan Parker", "Jamie Weston", "Morgan Chase"
    ]
    return random.choice(fallbacks)


def parse_session_file(content: str) -> List[dict]:
    """
    Parse session file content.
    Supports formats:
    - Phone: +XXXXXXXXXXXX | Format: TELETHON\\n<session_string>
    - Raw session strings (one per line)
    
    Returns list of dicts: [{phone, session_string}, ...]
    """
    accounts = []
    lines = content.strip().split("\n")
    i = 0
    
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        
        # Format: Phone: +XXXXXXXXXXXX | Format: TELETHON
        if line.startswith("Phone:") and "Format: TELETHON" in line:
            phone_match = re.search(r"Phone:\s*(\+?\d[\d\s\-]*)", line)
            phone = phone_match.group(1).strip() if phone_match else None
            if phone:
                phone = re.sub(r'[\s\-]', '', phone)
            
            # Next non-empty line should be the session string
            if i + 1 < len(lines):
                session_str = lines[i + 1].strip()
                if session_str and not session_str.startswith("Phone:"):
                    accounts.append({
                        "phone": phone,
                        "session_string": session_str,
                        "source": "session_file"
                    })
                    i += 2
                    continue
        else:
            # Raw session string (long base64-like string)
            if len(line) > 40 and not line.startswith("Phone:"):
                accounts.append({
                    "phone": None,
                    "session_string": line,
                    "source": "session_file"
                })
        i += 1
    
    return accounts


async def validate_session_string(session_str: str) -> Tuple[bool, str, dict]:
    """
    Validate a session string by connecting and getting user info.
    Returns (is_valid, message, user_info_dict).
    """
    client = await create_telethon_client(session_str)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            return False, "❌ Session is not authorized / expired.", {}
        
        me = await client.get_me()
        phone = getattr(me, "phone", None)
        # Update name from name.txt
        await update_account_name(client)
        
        await client.disconnect()
        
        user_info = {
            "user_id": me.id,
            "phone": phone,
            "username": me.username,
            "first_name": me.first_name or "",
            "last_name": me.last_name or "",
        }
        return True, f"✅ Valid session: @{me.username or 'N/A'} ({phone or 'N/A'})", user_info
    
    except Exception as e:
        try:
            await client.disconnect()
        except Exception:
            pass
        return False, f"❌ Invalid session: {str(e)}", {}


async def save_account_to_db(
    session_string: str,
    phone: Optional[str] = None,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    added_by: Optional[int] = None,
    source: str = "phone_otp"
) -> Tuple[bool, str]:
    """
    Save an account to MongoDB.
    Checks for duplicates before saving.
    """
    # Check if session already exists
    existing = db.accounts.find_one({"session_string": session_string})
    if existing:
        return False, "❌ This account (session) is already added."
    
    # Check by phone if available
    if phone:
        existing_phone = db.accounts.find_one({"phone": phone})
        if existing_phone:
            return False, f"❌ Account with phone {phone} is already in the database."
    
    # Check by user_id if available
    if user_id:
        existing_id = db.accounts.find_one({"user_id": user_id})
        if existing_id:
            return False, f"❌ Account (ID: {user_id}) is already in the database."
    
    # Get a random name for the account
    display_name = get_random_name()
    
    account_doc = {
        "session_string": session_string,
        "phone": phone,
        "user_id": user_id,
        "username": username,
        "display_name": display_name,
        "status": "connected",
        "source": source,
        "added_by": added_by,
        "added_at": __import__('datetime').datetime.utcnow(),
        "is_online": False,
        "last_seen_mode": None,
        "join_target": None,
        "total_joins": 0,
        "total_views": 0,
        "total_reactions": 0,
    }
    
    db.accounts.insert_one(account_doc)
    return True, f"✅ Account {'(' + phone + ') ' if phone else ''}added successfully as '{display_name}'!"


async def add_account_via_tdata(zip_path: str, added_by: Optional[int] = None) -> Tuple[bool, str, Optional[str]]:
    """
    Add accounts from a tdata folder (zipped).
    Uses opentele library to convert tdata to Telethon session.
    Returns (success, message, session_string).
    """
    extract_dir = tempfile.mkdtemp()
    try:
        # Extract zip
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(extract_dir)
        
        # Find tdata folder
        tdata_path = None
        for root, dirs, files in os.walk(extract_dir):
            if 'auth_data' in files or 'auth' in files or any(f.startswith('D877F783D5D3EF8C') for f in files):
                tdata_path = root
                break
            # Check if any directory name contains 'tdata'
            for d in dirs:
                if 'tdata' in d.lower():
                    tdata_path = os.path.join(root, d)
                    break
            if tdata_path:
                break
        
        if not tdata_path:
            # Try the extraction root directly
            tdata_path = extract_dir
        
        try:
            from opentele.td import TDesktop
            from opentele.api import UseCurrentSession
            from telethon.sessions import StringSession
            
            tdesk = TDesktop(tdata_path)
            if not tdesk.isLoaded():
                return False, "❌ Failed to load tdata folder. It may be corrupted or empty.", None
            
            # Convert to Telethon client
            client = await tdesk.ToTelethon(
                session=StringSession(),
                flag=UseCurrentSession
            )
            
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                return False, "❌ TData session is not authorized.", None
            
            me = await client.get_me()
            phone = getattr(me, "phone", None)
            
            # Get the session string
            session_str = client.session.save()
            
            # Update profile name
            await update_account_name(client)
            
            await client.disconnect()
            
            # Save to DB
            success, msg = await save_account_to_db(
                session_string=session_str,
                phone=phone,
                user_id=me.id,
                username=me.username,
                added_by=added_by,
                source="tdata"
            )
            
            if success:
                return True, f"✅ TData account added: @{me.username or 'N/A'} ({phone or 'N/A'})", session_str
            else:
                return False, msg, session_str
                
        except ImportError:
            return False, "❌ 'opentele' library not installed. Install with: pip install opentele", None
        except Exception as e:
            return False, f"❌ TData conversion failed: {str(e)}", None
    
    except zipfile.BadZipFile:
        return False, "❌ Invalid zip file.", None
    except Exception as e:
        return False, f"❌ Error processing tdata: {str(e)}", None
    finally:
        # Cleanup temp directory
        try:
            import shutil
            shutil.rmtree(extract_dir, ignore_errors=True)
        except Exception:
            pass


async def get_account_count() -> dict:
    """Get account statistics from the database."""
    total = db.accounts.count_documents({})
    connected = db.accounts.count_documents({"status": "connected"})
    disconnected = db.accounts.count_documents({"status": "disconnected"})
    return {
        "total": total,
        "connected": connected,
        "disconnected": disconnected,
    }


async def get_all_connected_accounts() -> list:
    """Get all connected accounts from the database."""
    return list(db.accounts.find({"status": "connected"}))


async def get_account_by_phone(phone: str) -> Optional[dict]:
    """Find an account by phone number."""
    return db.accounts.find_one({"phone": phone})


async def get_account_by_session(session_str: str) -> Optional[dict]:
    """Find an account by session string."""
    return db.accounts.find_one({"session_string": session_str})


async def update_account_status(phone: str, status: str) -> None:
    """Update an account's status."""
    db.accounts.update_one(
        {"phone": phone},
        {"$set": {"status": status}}
    )


async def delete_account(phone: str) -> bool:
    """Delete an account from the database."""
    result = db.accounts.delete_one({"phone": phone})
    return result.deleted_count > 0


async def delete_account_by_id(user_id: int) -> bool:
    """Delete an account by user ID."""
    result = db.accounts.delete_one({"user_id": user_id})
    return result.deleted_count > 0

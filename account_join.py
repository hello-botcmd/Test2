"""
account_join.py - Join channels/groups with 3 distinct modes.
Handles randomized joining with configurable delays and mode distribution.
"""
import asyncio
import random
import logging
from typing import List, Optional, Tuple
from datetime import datetime

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateStatusRequest
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.errors import (
    FloodWaitError,
    ChannelPrivateError,
    InviteHashExpiredError,
    InviteHashInvalidError,
    UserAlreadyParticipantError,
    ChannelsTooMuchError,
    InviteRequestSentError,
)

import config
from database import db
from account_load import create_telethon_client, connect_and_check, update_account_name

logger = logging.getLogger(__name__)


# --- Mode Assignment ---
def assign_join_modes(num_accounts: int) -> List[int]:
    """
    Assign join modes to accounts based on configured percentages.
    Returns a list of mode numbers (1, 2, or 3) of length num_accounts.
    
    Mode 1: Always Online (20%)  - stays online permanently
    Mode 2: Last Seen Recently (40%) - joins and shows "last seen recently"
    Mode 3: Offline after 2 mins (40%) - goes offline after 2 mins
    """
    mode_1_count = max(1, round(num_accounts * config.JOIN_MODE_1_PERCENT / 100))
    mode_2_count = max(1, round(num_accounts * config.JOIN_MODE_2_PERCENT / 100))
    mode_3_count = num_accounts - mode_1_count - mode_2_count
    
    # Ensure at least 1 in each mode if possible
    while mode_3_count < 0 and mode_2_count > 1:
        mode_2_count -= 1
        mode_3_count += 1
    while mode_3_count < 0 and mode_1_count > 1:
        mode_1_count -= 1
        mode_3_count += 1
    
    modes = [1] * mode_1_count + [2] * mode_2_count + [3] * mode_3_count
    
    # Shuffle modes randomly
    random.shuffle(modes)
    
    # Trim or pad to exact count
    if len(modes) > num_accounts:
        modes = modes[:num_accounts]
    while len(modes) < num_accounts:
        modes.append(random.choice([1, 2, 3]))
    
    return modes


# --- Target Parsing ---
def parse_target(target: str) -> Tuple[str, Optional[str]]:
    """
    Parse join target.
    Returns (type, identifier) where type is 'public', 'private', or 'unknown'.
    """
    target = target.strip()
    
    # Private invite link: t.me/+hash or t.me/joinchat/hash
    invite_hash = None
    import re
    
    # t.me/+ABC123
    match = re.search(r't\.me/\+([a-zA-Z0-9_-]+)', target)
    if match:
        return 'private', match.group(1)
    
    # t.me/joinchat/ABC123
    match = re.search(r't\.me/joinchat/([a-zA-Z0-9_-]+)', target)
    if match:
        return 'private', match.group(1)
    
    # tg://join?invite=ABC123
    match = re.search(r'invite=([a-zA-Z0-9_-]+)', target)
    if match:
        return 'private', match.group(1)
    
    # @username or t.me/username (public)
    match = re.search(r'@?([a-zA-Z][a-zA-Z0-9_]{3,})', target)
    if match:
        return 'public', match.group(1)
    
    return 'unknown', target


# --- Join Functions per Mode ---
async def join_mode_1_always_online(
    client: TelegramClient,
    target_type: str,
    target_id: str,
    cancel_event: asyncio.Event
) -> Tuple[bool, str]:
    """
    Mode 1: Account comes online, joins, and stays online permanently.
    Periodically sends UpdateStatusRequest to keep the green dot active.
    """
    try:
        # Step 1: Come online
        await client(UpdateStatusRequest(offline=False))
        await asyncio.sleep(1)
        
        # Step 2: Join the target
        if target_type == 'public':
            entity = await client.get_entity(target_id)
            await client(JoinChannelRequest(channel=entity))
        else:
            await client(ImportChatInviteRequest(hash=target_id))
        
        # Step 3: Start keep-alive loop in background
        asyncio.create_task(_keep_online_loop(client, cancel_event))
        
        return True, "✅ Joined (Mode 1 - Always Online)"
    
    except UserAlreadyParticipantError:
        return True, "✅ Already a member (Mode 1)"
    except FloodWaitError as e:
        return False, f"⏳ Flood wait {e.seconds}s"
    except ChannelPrivateError:
        return False, "❌ Private channel - cannot join"
    except InviteHashExpiredError:
        return False, "❌ Invite link expired"
    except InviteHashInvalidError:
        return False, "❌ Invalid invite link"
    except ChannelsTooMuchError:
        return False, "❌ Joined too many channels"
    except InviteRequestSentError:
        return False, "⏳ Join request sent (pending approval)"
    except Exception as e:
        return False, f"❌ Error: {str(e)[:60]}"


async def join_mode_2_last_seen_recently(
    client: TelegramClient,
    target_type: str,
    target_id: str,
) -> Tuple[bool, str]:
    """
    Mode 2: Account joins showing "last seen recently".
    The account comes online just long enough to join, then disconnects.
    Telegram will show "last seen recently" when it briefly comes online.
    """
    try:
        # Come online briefly
        await client(UpdateStatusRequest(offline=False))
        await asyncio.sleep(0.5)
        
        # Join the target
        if target_type == 'public':
            entity = await client.get_entity(target_id)
            await client(JoinChannelRequest(channel=entity))
        else:
            await client(ImportChatInviteRequest(hash=target_id))
        
        # Disconnect so Telegram shows "last seen recently"
        # We don't explicitly set offline - just disconnect
        # Telegram will show "last seen recently" after a brief online period
        
        return True, "✅ Joined (Mode 2 - Last Seen Recently)"
    
    except UserAlreadyParticipantError:
        return True, "✅ Already a member (Mode 2)"
    except FloodWaitError as e:
        return False, f"⏳ Flood wait {e.seconds}s"
    except ChannelPrivateError:
        return False, "❌ Private channel"
    except InviteHashExpiredError:
        return False, "❌ Invite expired"
    except InviteHashInvalidError:
        return False, "❌ Invalid invite"
    except ChannelsTooMuchError:
        return False, "❌ Too many channels"
    except InviteRequestSentError:
        return False, "⏳ Request sent"
    except Exception as e:
        return False, f"❌ Error: {str(e)[:60]}"


async def join_mode_3_offline_after_2mins(
    client: TelegramClient,
    target_type: str,
    target_id: str,
    cancel_event: asyncio.Event
) -> Tuple[bool, str]:
    """
    Mode 3: Account joins, stays online for 2 minutes, then goes offline.
    After going offline, Telegram shows "last seen X minutes ago".
    """
    try:
        # Come online
        await client(UpdateStatusRequest(offline=False))
        await asyncio.sleep(1)
        
        # Join the target
        if target_type == 'public':
            entity = await client.get_entity(target_id)
            await client(JoinChannelRequest(channel=entity))
        else:
            await client(ImportChatInviteRequest(hash=target_id))
        
        # Stay online for 2 minutes, checking cancel event
        try:
            await asyncio.wait_for(
                _wait_with_cancel(config.OFFLINE_AFTER_SECONDS, cancel_event),
                timeout=config.OFFLINE_AFTER_SECONDS + 10
            )
        except asyncio.TimeoutError:
            pass
        
        # Go offline - explicitly set status to offline
        if not cancel_event.is_set():
            await client(UpdateStatusRequest(offline=True))
        
        return True, "✅ Joined (Mode 3 - Offline after 2 mins)"
    
    except UserAlreadyParticipantError:
        return True, "✅ Already a member (Mode 3)"
    except FloodWaitError as e:
        return False, f"⏳ Flood wait {e.seconds}s"
    except ChannelPrivateError:
        return False, "❌ Private channel"
    except InviteHashExpiredError:
        return False, "❌ Invite expired"
    except InviteHashInvalidError:
        return False, "❌ Invalid invite"
    except ChannelsTooMuchError:
        return False, "❌ Too many channels"
    except InviteRequestSentError:
        return False, "⏳ Request sent"
    except Exception as e:
        return False, f"❌ Error: {str(e)[:60]}"


async def _keep_online_loop(client: TelegramClient, cancel_event: asyncio.Event) -> None:
    """Keep account online by periodically sending UpdateStatusRequest."""
    while not cancel_event.is_set():
        try:
            await client(UpdateStatusRequest(offline=False))
        except Exception:
            break  # Client likely disconnected
        try:
            await asyncio.wait_for(
                asyncio.sleep(config.ONLINE_KEEPALIVE_INTERVAL),
                timeout=config.ONLINE_KEEPALIVE_INTERVAL + 5
            )
        except asyncio.TimeoutError:
            continue
        except Exception:
            break


async def _wait_with_cancel(seconds: int, cancel_event: asyncio.Event) -> None:
    """Sleep with cancel check at intervals."""
    interval = 2
    elapsed = 0
    while elapsed < seconds and not cancel_event.is_set():
        await asyncio.sleep(interval)
        elapsed += interval


# --- Main Join Orchestrator ---
async def execute_join(
    target: str,
    min_delay: float,
    max_delay: float,
    progress_callback=None,
    cancel_event: asyncio.Event = None
) -> dict:
    """
    Execute the full join operation across all connected accounts.
    
    Args:
        target: Channel username, invite link, or group identifier
        min_delay: Minimum delay between joins (seconds)
        max_delay: Maximum delay between joins (seconds)
        progress_callback: Async callable(status_msg, progress_percent)
        cancel_event: Event to signal cancellation
    
    Returns:
        dict with join results
    """
    if cancel_event is None:
        cancel_event = asyncio.Event()
    
    # Parse target
    target_type, target_id = parse_target(target)
    if target_type == 'unknown':
        return {"success": False, "message": "❌ Invalid target. Use @username, t.me/username, or invite link."}
    
    # Get all connected accounts
    accounts = list(db.accounts.find({"status": "connected"}))
    if not accounts:
        return {"success": False, "message": "❌ No connected accounts in the database."}
    
    # Shuffle accounts for randomness
    random.shuffle(accounts)
    
    # Assign modes
    modes = assign_join_modes(len(accounts))
    
    # Results tracking
    results = {
        "total": len(accounts),
        "success": 0,
        "failed": 0,
        "mode_1_count": 0,
        "mode_2_count": 0,
        "mode_3_count": 0,
        "details": []
    }
    
    if progress_callback:
        await progress_callback(f"🎯 Target: {target} ({target_type})\n"
                                f"👥 Accounts: {len(accounts)} | Starting join process...", 0)
    
    for idx, (account, mode) in enumerate(zip(accounts, modes)):
        if cancel_event.is_set():
            if progress_callback:
                await progress_callback("⛔ Join operation cancelled by user.", 
                                        int((idx / len(accounts)) * 100))
            break
        
        phone = account.get("phone", "Unknown")
        session_str = account.get("session_string")
        display_name = account.get("display_name", "Unknown")
        
        # Calculate delay before this join (except first)
        delay = 0
        if idx > 0:
            delay = round(random.uniform(min_delay, max_delay), 1)
        
        if progress_callback:
            mode_names = {1: "Always Online", 2: "Last Seen Recently", 3: "Offline after 2min"}
            status = f"[{idx+1}/{len(accounts)}] ⏳ {display_name} ({phone}) → Mode {mode_names[mode]}"
            if delay > 0:
                status += f" | Waiting {delay}s..."
            await progress_callback(status, int((idx / len(accounts)) * 100))
        
        # Wait for the delay
        if delay > 0:
            try:
                await asyncio.wait_for(
                    _wait_with_cancel(int(delay), cancel_event),
                    timeout=delay + 5
                )
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        
        if cancel_event.is_set():
            break
        
        # Execute join
        client = await create_telethon_client(session_str)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                results["failed"] += 1
                results["details"].append({
                    "phone": phone,
                    "display_name": display_name,
                    "mode": mode,
                    "success": False,
                    "message": "Session expired"
                })
                if progress_callback:
                    await progress_callback(f"[{idx+1}/{len(accounts)}] ❌ {display_name} - Session expired",
                                            int(((idx + 1) / len(accounts)) * 100))
                continue
            
            # Update profile name before joining
            await update_account_name(client)
            
            # Perform join based on mode
            if mode == 1:
                success, msg = await join_mode_1_always_online(client, target_type, target_id, cancel_event)
                if success:
                    results["mode_1_count"] += 1
            elif mode == 2:
                success, msg = await join_mode_2_last_seen_recently(client, target_type, target_id)
                if success:
                    results["mode_2_count"] += 1
            else:  # mode 3
                success, msg = await join_mode_3_offline_after_2mins(client, target_type, target_id, cancel_event)
                if success:
                    results["mode_3_count"] += 1
            
            if success:
                results["success"] += 1
                # Update account stats
                db.accounts.update_one(
                    {"_id": account["_id"]},
                    {"$inc": {"total_joins": 1}, "$set": {"last_join": datetime.utcnow()}}
                )
            else:
                results["failed"] += 1
            
            results["details"].append({
                "phone": phone,
                "display_name": display_name,
                "mode": mode,
                "success": success,
                "message": msg
            })
            
            if progress_callback:
                icon = "✅" if success else "❌"
                await progress_callback(
                    f"[{idx+1}/{len(accounts)}] {icon} {display_name} - {msg}",
                    int(((idx + 1) / len(accounts)) * 100)
                )
        
        except Exception as e:
            results["failed"] += 1
            results["details"].append({
                "phone": phone,
                "display_name": display_name,
                "mode": mode,
                "success": False,
                "message": str(e)[:60]
            })
            if progress_callback:
                await progress_callback(f"[{idx+1}/{len(accounts)}] ❌ {display_name} - Error: {str(e)[:60]}",
                                        int(((idx + 1) / len(accounts)) * 100))
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
    
    return results

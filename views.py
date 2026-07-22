"""
views.py - View boosting for Telegram channel posts.
Uses GetMessagesViewsRequest with increment=True to boost view counts.
"""
import asyncio
import random
import re
import logging
from typing import Optional, List, Tuple
from datetime import datetime

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import GetMessagesViewsRequest
from telethon.errors import FloodWaitError

import config
from database import db
from account_load import create_telethon_client, connect_and_check

logger = logging.getLogger(__name__)


def parse_post_link(link: str) -> Tuple[Optional[str], Optional[int]]:
    """
    Parse a Telegram post link.
    Returns (channel_identifier, message_id).
    
    Supports:
    - https://t.me/username/1234          (public)
    - https://t.me/c/123456789/1234       (private via channel ID)
    - t.me/username/1234
    - t.me/c/123456789/1234
    """
    link = link.strip()
    
    # Private channel: t.me/c/CHANNEL_ID/MSG_ID
    match = re.search(r't\.me/c/(\d+)/(\d+)', link)
    if match:
        channel_id = int(match.group(1))
        msg_id = int(match.group(2))
        return channel_id, msg_id
    
    # Public channel: t.me/USERNAME/MSG_ID
    match = re.search(r't\.me/([a-zA-Z][a-zA-Z0-9_]+)/(\d+)', link)
    if match:
        username = match.group(1)
        msg_id = int(match.group(2))
        return username, msg_id
    
    return None, None


async def boost_views(
    links: List[str],
    total_views_desired: int,
    progress_callback=None,
    cancel_event: asyncio.Event = None
) -> dict:
    """
    Boost views on one or more posts using connected accounts.
    
    Each account can increment views ~1-2 times per day per post.
    Distributes the total desired views across all available accounts.
    
    Args:
        links: List of post links to boost
        total_views_desired: Total number of views to add
        progress_callback: Async callable for progress updates
        cancel_event: Event to signal cancellation
    
    Returns:
        dict with results
    """
    if cancel_event is None:
        cancel_event = asyncio.Event()
    
    # Parse all links
    parsed_links = []
    for link in links:
        channel_id, msg_id = parse_post_link(link)
        if channel_id is None or msg_id is None:
            if progress_callback:
                await progress_callback(f"❌ Invalid link: {link}", 0)
            continue
        parsed_links.append((channel_id, msg_id, link))
    
    if not parsed_links:
        return {"success": False, "message": "❌ No valid post links provided."}
    
    # Get all connected accounts
    accounts = list(db.accounts.find({"status": "connected"}))
    if not accounts:
        return {"success": False, "message": "❌ No connected accounts available."}
    
    random.shuffle(accounts)
    
    # Calculate views per account
    # Each account can attempt multiple view increments with delays
    # But Telegram limits this to 1-2 per day per account per post
    views_per_account = max(1, total_views_desired // len(accounts))
    remaining_views = total_views_desired - (views_per_account * len(accounts))
    
    # Distribute remaining views
    views_assignment = [views_per_account] * len(accounts)
    for i in range(remaining_views):
        if i < len(views_assignment):
            views_assignment[i] += 1
    
    results = {
        "total_links": len(parsed_links),
        "total_accounts": len(accounts),
        "views_requested": total_views_desired,
        "views_achieved": 0,
        "success": 0,
        "failed": 0,
        "details": []
    }
    
    for link_idx, (channel_id, msg_id, original_link) in enumerate(parsed_links):
        if cancel_event.is_set():
            if progress_callback:
                await progress_callback("⛔ View boost cancelled.", 
                                        int((link_idx / len(parsed_links)) * 100))
            break
        
        if progress_callback:
            await progress_callback(f"📊 Boosting: {original_link}", 
                                    int((link_idx / len(parsed_links)) * 100))
        
        for acc_idx, (account, views_to_add) in enumerate(zip(accounts, views_assignment)):
            if cancel_event.is_set():
                break
            
            phone = account.get("phone", "Unknown")
            display_name = account.get("display_name", "Unknown")
            session_str = account.get("session_string")
            
            client = await create_telethon_client(session_str)
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    results["failed"] += 1
                    continue
                
                # Get the entity
                try:
                    if isinstance(channel_id, int):
                        entity = await client.get_entity(channel_id)
                    else:
                        entity = await client.get_entity(channel_id)
                except Exception as e:
                    # Try to join channel if not member
                    try:
                        if isinstance(channel_id, int):
                            from telethon.tl.functions.channels import JoinChannelRequest
                            entity = await client.get_entity(channel_id)
                        else:
                            entity = await client.get_entity(channel_id)
                    except Exception:
                        results["failed"] += 1
                        continue
                
                # Attempt to increment views (multiple times per account with delays)
                views_added = 0
                for v in range(min(views_to_add, 3)):  # Max 3 attempts per account to be safe
                    if cancel_event.is_set():
                        break
                    
                    try:
                        await client(GetMessagesViewsRequest(
                            peer=entity,
                            id=[msg_id],
                            increment=True
                        ))
                        views_added += 1
                        results["views_achieved"] += 1
                        await asyncio.sleep(random.uniform(2, 5))
                    except FloodWaitError as e:
                        if progress_callback:
                            await progress_callback(f"⏳ Rate limited on {display_name}, waiting {e.seconds}s...",
                                                    int(((link_idx + 1) / len(parsed_links)) * 100))
                        await asyncio.sleep(min(e.seconds, 30))
                        break
                    except Exception:
                        break
                
                if views_added > 0:
                    results["success"] += 1
                    db.accounts.update_one(
                        {"_id": account["_id"]},
                        {"$inc": {"total_views": views_added}}
                    )
                else:
                    results["failed"] += 1
                
                results["details"].append({
                    "phone": phone,
                    "display_name": display_name,
                    "link": original_link,
                    "views_added": views_added
                })
                
                if progress_callback:
                    await progress_callback(
                        f"[{acc_idx+1}/{len(accounts)}] {'✅' if views_added > 0 else '❌'} "
                        f"{display_name} → +{views_added} views",
                        int(((link_idx + 1) / len(parsed_links)) * 100)
                    )
                
                # Small delay between accounts
                await asyncio.sleep(random.uniform(1, 3))
            
            except Exception as e:
                results["failed"] += 1
                logger.error(f"View boost error for {phone}: {e}")
            finally:
                try:
                    await client.disconnect()
                except Exception:
                    pass
    
    return results

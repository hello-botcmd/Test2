"""
reaction.py - Reaction management for Telegram posts.
Supports single and mixed reactions across multiple accounts.
"""
import asyncio
import random
import logging
from typing import List, Optional, Tuple
from datetime import datetime

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji
from telethon.errors import FloodWaitError

import config
from database import db
from account_load import create_telethon_client, connect_and_check
from views import parse_post_link

logger = logging.getLogger(__name__)


async def send_reactions(
    link: str,
    reactions: List[str],
    total_reactions_desired: int,
    progress_callback=None,
    cancel_event: asyncio.Event = None
) -> dict:
    """
    Add reactions to a Telegram post using connected accounts.
    
    Args:
        link: Post link (t.me/username/1234 or t.me/c/123456/1234)
        reactions: List of emoji reactions to use (e.g., ["❤️", "👍", "🔥"])
        total_reactions_desired: Number of accounts to react
        progress_callback: Async callable for progress
        cancel_event: Event for cancellation
    
    Returns:
        dict with results
    """
    if cancel_event is None:
        cancel_event = asyncio.Event()
    
    # Parse the link
    channel_id, msg_id = parse_post_link(link)
    if channel_id is None or msg_id is None:
        return {"success": False, "message": "❌ Invalid post link format."}
    
    # Get all connected accounts
    accounts = list(db.accounts.find({"status": "connected"}))
    if not accounts:
        return {"success": False, "message": "❌ No connected accounts available."}
    
    random.shuffle(accounts)
    
    # Determine how many accounts to use
    accounts_to_use = min(total_reactions_desired, len(accounts))
    selected_accounts = accounts[:accounts_to_use]
    
    results = {
        "link": link,
        "reactions_available": reactions,
        "total_requested": total_reactions_desired,
        "total_sent": 0,
        "success": 0,
        "failed": 0,
        "details": []
    }
    
    if progress_callback:
        await progress_callback(
            f"🎯 Post: {link}\n"
            f"👥 Accounts to react: {accounts_to_use}\n"
            f"💜 Reactions: {' '.join(reactions)}"
            f"\nStarting...", 0
        )
    
    for idx, account in enumerate(selected_accounts):
        if cancel_event.is_set():
            if progress_callback:
                await progress_callback("⛔ Reaction operation cancelled.", 
                                        int((idx / accounts_to_use) * 100))
            break
        
        phone = account.get("phone", "Unknown")
        display_name = account.get("display_name", "Unknown")
        session_str = account.get("session_string")
        
        # Pick a random reaction from the list
        reaction_emoji = random.choice(reactions)
        
        client = await create_telethon_client(session_str)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                results["failed"] += 1
                if progress_callback:
                    await progress_callback(
                        f"[{idx+1}/{accounts_to_use}] ❌ {display_name} - Session expired",
                        int(((idx + 1) / accounts_to_use) * 100)
                    )
                continue
            
            # Get the entity
            try:
                if isinstance(channel_id, int):
                    entity = await client.get_entity(channel_id)
                else:
                    entity = await client.get_entity(channel_id)
            except Exception:
                # Try joining first
                try:
                    from telethon.tl.functions.channels import JoinChannelRequest
                    from telethon.tl.functions.messages import ImportChatInviteRequest
                    if isinstance(channel_id, int):
                        entity = await client.get_entity(channel_id)
                    else:
                        entity = await client.get_entity(channel_id)
                except Exception as e:
                    results["failed"] += 1
                    if progress_callback:
                        await progress_callback(
                            f"[{idx+1}/{accounts_to_use}] ❌ {display_name} - Cannot access channel",
                            int(((idx + 1) / accounts_to_use) * 100)
                        )
                    continue
            
            # Send the reaction
            try:
                await client(SendReactionRequest(
                    peer=entity,
                    msg_id=msg_id,
                    reaction=[ReactionEmoji(emoticon=reaction_emoji)]
                ))
                
                results["total_sent"] += 1
                results["success"] += 1
                
                # Update account stats
                db.accounts.update_one(
                    {"_id": account["_id"]},
                    {"$inc": {"total_reactions": 1}}
                )
                
                results["details"].append({
                    "phone": phone,
                    "display_name": display_name,
                    "reaction": reaction_emoji,
                    "success": True
                })
                
                if progress_callback:
                    await progress_callback(
                        f"[{idx+1}/{accounts_to_use}] ✅ {display_name} → {reaction_emoji}",
                        int(((idx + 1) / accounts_to_use) * 100)
                    )
                
            except FloodWaitError as e:
                results["failed"] += 1
                if progress_callback:
                    await progress_callback(
                        f"[{idx+1}/{accounts_to_use}] ⏳ {display_name} - Flood wait {e.seconds}s",
                        int(((idx + 1) / accounts_to_use) * 100)
                    )
                await asyncio.sleep(min(e.seconds, 10))
            
            except Exception as e:
                results["failed"] += 1
                results["details"].append({
                    "phone": phone,
                    "display_name": display_name,
                    "reaction": reaction_emoji,
                    "success": False,
                    "error": str(e)[:60]
                })
                if progress_callback:
                    await progress_callback(
                        f"[{idx+1}/{accounts_to_use}] ❌ {display_name} - Error",
                        int(((idx + 1) / accounts_to_use) * 100)
                    )
            
            # Small delay between reactions
            await asyncio.sleep(random.uniform(1, 2))
        
        except Exception as e:
            results["failed"] += 1
            logger.error(f"Reaction error for {phone}: {e}")
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
    
    return results

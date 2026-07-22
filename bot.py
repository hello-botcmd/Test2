#!/usr/bin/env python3
"""
bot.py - Main Telegram Bot for the Account Manager.
Premium UI with inline keyboards and conversation handlers.
"""
import asyncio
import logging
import os
import sys
import traceback
from datetime import datetime
from typing import Optional

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, BotCommand
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler, ContextTypes
)
from telegram.constants import ParseMode

import config
from database import db
import account_load
import account_join
import reaction as reaction_module
import views as views_module

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Conversation States ---
(
    MAIN_MENU,
    WAITING_PHONE,
    WAITING_OTP,
    WAITING_2FA,
    WAITING_SESSION_FILE,
    WAITING_TDATA_FILE,
    WAITING_JOIN_TARGET,
    WAITING_JOIN_DELAY_MIN,
    WAITING_JOIN_DELAY_MAX,
    WAITING_VIEWS_LINKS,
    WAITING_VIEWS_COUNT,
    WAITING_REACTION_LINK,
    WAITING_REACTION_TYPES,
    WAITING_REACTION_COUNT,
    WAITING_CONFIRM,
) = range(15)

# --- Global Cancel Event ---
cancel_event = asyncio.Event()


# ============================================================
# AUTHORIZATION CHECK
# ============================================================
def is_authorized(user_id: int) -> bool:
    """Check if user is authorized (owner or admin)."""
    return user_id == config.OWNER_ID or user_id in config.ADMIN_IDS


async def auth_check(update: Update) -> bool:
    """Check authorization and send error if not authorized."""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.effective_message.reply_text(
            "⛔ **Unauthorized**\n\nYou don't have permission to use this bot.",
            parse_mode=ParseMode.MARKDOWN
        )
        return False
    return True


# ============================================================
# UI HELPERS
# ============================================================
def build_main_menu():
    """Build the premium main menu keyboard."""
    keyboard = [
        [InlineKeyboardButton("📱 Add Account", callback_data="add_account")],
        [InlineKeyboardButton("🔗 Join Channel/Group", callback_data="join")],
        [InlineKeyboardButton("👁 View Boost", callback_data="views")],
        [InlineKeyboardButton("💜 Reactions", callback_data="reactions")],
        [InlineKeyboardButton("🟢 All Online", callback_data="all_online")],
        [InlineKeyboardButton("📊 Total Accounts", callback_data="total_accounts")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_add_account_menu():
    """Build the add account submenu."""
    keyboard = [
        [InlineKeyboardButton("📞 Phone + OTP", callback_data="add_phone")],
        [InlineKeyboardButton("📄 Session File", callback_data="add_session_file")],
        [InlineKeyboardButton("📁 TData Folder", callback_data="add_tdata")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_cancel_keyboard():
    """Build a cancel-only keyboard."""
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_op")]]
    return InlineKeyboardMarkup(keyboard)


# ============================================================
# COMMAND HANDLERS
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /start command - show welcome and main menu."""
    if not await auth_check(update):
        return ConversationHandler.END
    
    user = update.effective_user
    welcome_text = (
        f"🌟 **Telegram Account Manager** 🌟\n\n"
        f"Welcome, {user.first_name}!\n\n"
        f"┌───────────────────────────┐\n"
        f"│  **_Premium Account Suite_**  │\n"
        f"└───────────────────────────┘\n\n"
        f"Select an option below to manage your Telegram accounts:\n\n"
        f"📱 **Add Account** — Add accounts via Phone/OTP, Session file, or TData\n"
        f"🔗 **Join** — Join channels/groups with randomized modes\n"
        f"👁 **View Boost** — Increase post view counts\n"
        f"💜 **Reactions** — Add reactions to posts\n"
        f"🟢 **All Online** — Set all accounts online\n"
        f"📊 **Stats** — View account statistics"
    )
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=build_main_menu(),
        parse_mode=ParseMode.MARKDOWN
    )
    
    return MAIN_MENU


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /cancel command - cancel any ongoing operation."""
    global cancel_event
    cancel_event.set()
    # Create a new event for future operations
    cancel_event = asyncio.Event()
    
    await update.message.reply_text(
        "⛔ **Operation Cancelled**\n\nAll ongoing operations have been stopped.",
        reply_markup=build_main_menu(),
        parse_mode=ParseMode.MARKDOWN
    )
    return MAIN_MENU


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /help command."""
    if not await auth_check(update):
        return ConversationHandler.END
    
    help_text = (
        "📖 **Help & Commands**\n\n"
        "`/start` — Open main menu\n"
        "`/cancel` — Cancel any running operation\n"
        "`/help` — Show this help\n"
        "`/stats` — Show account statistics\n\n"
        "**Features:**\n"
        "• **Add Account**: Phone+OTP+2FA, Session file, or TData folder\n"
        "• **Join**: Join channels/groups with 3 online modes\n"
        "• **View Boost**: Increase post views\n"
        "• **Reactions**: Add reactions to posts\n"
        "• **All Online**: Set all accounts permanently online\n\n"
        "⚡ Powered by HackerAI"
    )
    
    await update.message.reply_text(
        help_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_main_menu()
    )
    return MAIN_MENU


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /stats command."""
    if not await auth_check(update):
        return ConversationHandler.END
    
    counts = await account_load.get_account_count()
    
    text = (
        "📊 **Account Statistics**\n\n"
        f"┌─────────────────────┐\n"
        f"│ 📦 Total: `{counts['total']}`\n"
        f"│ 🟢 Connected: `{counts['connected']}`\n"
        f"│ 🔴 Disconnected: `{counts['disconnected']}`\n"
        f"└─────────────────────┘"
    )
    
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_main_menu()
    )
    return MAIN_MENU
  # ============================================================
# CALLBACK QUERY HANDLER
# ============================================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle all inline keyboard button presses."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    # --- Back to Main Menu ---
    if data == "back_main":
        await query.edit_message_text(
            "🌟 **Telegram Account Manager** 🌟\n\nSelect an option:",
            reply_markup=build_main_menu(),
            parse_mode=ParseMode.MARKDOWN
        )
        return MAIN_MENU
    
    # --- Add Account Menu ---
    if data == "add_account":
        await query.edit_message_text(
            "📱 **Add Account**\n\nChoose how you'd like to add accounts:",
            reply_markup=build_add_account_menu(),
            parse_mode=ParseMode.MARKDOWN
        )
        return MAIN_MENU
    
    # --- Add via Phone ---
    if data == "add_phone":
        await query.edit_message_text(
            "📞 **Add via Phone + OTP**\n\n"
            "Please enter the phone number in international format.\n"
            "Example: `+917248843065`\n\n"
            "Send `/cancel` to abort.",
            reply_markup=build_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_PHONE
    
    # --- Add via Session File ---
    if data == "add_session_file":
        await query.edit_message_text(
            "📄 **Add via Session File**\n\n"
            "Please upload a `.txt` file containing session strings.\n\n"
            "Supported formats:\n"
            "```\n"
            "Phone: +917248843065 | Format: TELETHON\n"
            "1BSABCyjyP_AF...session_string_here...\n"
            "```\n\n"
            "Or just raw session strings (one per line).\n\n"
            "Send `/cancel` to abort.",
            reply_markup=build_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_SESSION_FILE
    
    # --- Add via TData ---
    if data == "add_tdata":
        await query.edit_message_text(
            "📁 **Add via TData Folder**\n\n"
            "Please upload a **ZIP** file containing the `tdata` folder.\n\n"
            "The tdata folder is typically located at:\n"
            "`%appdata%\\Telegram Desktop\\tdata`\n\n"
            "Send `/cancel` to abort.",
            reply_markup=build_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_TDATA_FILE
    
    # --- Join ---
    if data == "join":
        await query.edit_message_text(
            "🔗 **Join Channel/Group**\n\n"
            "Enter the target channel or group:\n\n"
            "• Public: `@username` or `t.me/username`\n"
            "• Private: Invite link `t.me/+hash` or `t.me/joinchat/hash`\n\n"
            "Send `/cancel` to abort.",
            reply_markup=build_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_JOIN_TARGET
    
    # --- Views ---
    if data == "views":
        await query.edit_message_text(
            "👁 **View Boost**\n\n"
            "Enter the post link(s) to boost views.\n"
            "You can send multiple links (one per line).\n\n"
            "Format: `t.me/username/1234` or `t.me/c/123456/1234`\n\n"
            "Send `/cancel` to abort.",
            reply_markup=build_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_VIEWS_LINKS
    
    # --- Reactions ---
    if data == "reactions":
        await query.edit_message_text(
            "💜 **Add Reactions**\n\n"
            "Enter the post link to add reactions:\n\n"
            "Format: `t.me/username/1234` or `t.me/c/123456/1234`\n\n"
            "Send `/cancel` to abort.",
            reply_markup=build_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_REACTION_LINK
    
    # --- All Online ---
    if data == "all_online":
        await handle_all_online(query)
        return MAIN_MENU
    
    # --- Total Accounts ---
    if data == "total_accounts":
        await handle_total_accounts(query)
        return MAIN_MENU
    
    # --- Cancel ---
    if data == "cancel_op":
        global cancel_event
        cancel_event.set()
        cancel_event = asyncio.Event()
        await query.edit_message_text(
            "⛔ Operation cancelled.",
            reply_markup=build_main_menu()
        )
        return MAIN_MENU
    
    return MAIN_MENU


# ============================================================
# FEATURE HANDLERS
# ============================================================
async def handle_all_online(query):
    """Set all accounts online permanently."""
    global cancel_event
    cancel_event = asyncio.Event()
    
    await query.edit_message_text(
        "🟢 **Setting all accounts online...**\n\nThis may take a moment.",
        parse_mode=ParseMode.MARKDOWN
    )
    
    accounts = await account_load.get_all_connected_accounts()
    if not accounts:
        await query.message.reply_text(
            "❌ No connected accounts found.",
            reply_markup=build_main_menu()
        )
        return
    
    success_count = 0
    fail_count = 0
    
    for i, account in enumerate(accounts):
        if cancel_event.is_set():
            break
        
        session_str = account.get("session_string")
        phone = account.get("phone", "Unknown")
        
        client = await account_load.create_telethon_client(session_str)
        try:
            await client.connect()
            if await client.is_user_authorized():
                await client(account_load.UpdateStatusRequest(offline=False))
                success_count += 1
            else:
                fail_count += 1
        except Exception:
            fail_count += 1
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
        
        if (i + 1) % 5 == 0:
            await query.message.reply_text(
                f"🟢 Progress: {i+1}/{len(accounts)} accounts processed..."
            )
    
    await query.message.reply_text(
        f"🟢 **All Online Complete**\n\n"
        f"✅ Success: `{success_count}`\n"
        f"❌ Failed: `{fail_count}`\n"
        f"{'⛔ Cancelled' if cancel_event.is_set() else '🎉 Done!'}",
        reply_markup=build_main_menu(),
        parse_mode=ParseMode.MARKDOWN
    )


async def handle_total_accounts(query):
    """Show total account statistics."""
    counts = await account_load.get_account_count()
    
    text = (
        "📊 **Account Statistics**\n\n"
        f"┌─────────────────────┐\n"
        f"│ 📦 **Total:** `{counts['total']}`\n"
        f"│ 🟢 **Connected:** `{counts['connected']}`\n"
        f"│ 🔴 **Disconnected:** `{counts['disconnected']}`\n"
        f"└─────────────────────┘\n\n"
        f"📋 _Last updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}_"
    )
    
    # Get a sample of accounts
    if counts['connected'] > 0:
        accounts = list(db.accounts.find({"status": "connected"}).limit(5))
        if accounts:
            text += "\n\n**Recent Accounts:**\n"
            for acc in accounts:
                name = acc.get("display_name", "Unknown")
                phone = acc.get("phone", "N/A") or "N/A"
                username = acc.get("username", "") or ""
                uname_str = f" (@{username})" if username else ""
                text += f"• {name} — `{phone}`{uname_str}\n"
    
    text += f"\n➕ _Total: {counts['total']} accounts_"
    
    await query.edit_message_text(
        text,
        reply_markup=build_main_menu(),
        parse_mode=ParseMode.MARKDOWN
  )
  # ============================================================
# MESSAGE HANDLERS - ACCOUNT ADDITION
# ============================================================
async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle phone number input."""
    phone = update.message.text.strip()
    
    # Validate phone format
    if not phone.startswith("+"):
        await update.message.reply_text(
            "❌ Invalid format. Please use international format starting with `+`.\n"
            "Example: `+917248843065`",
            parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_PHONE
    
    # Store phone in context
    context.user_data["phone"] = phone
    
    # Send OTP
    success, msg, client = await account_load.send_otp(phone)
    
    if success:
        context.user_data["otp_client"] = client
        await update.message.reply_text(
            f"✅ **OTP Sent**\n\n{msg}\n\n"
            f"Please enter the OTP code you received:\n\n"
            f"Send `/cancel` to abort.",
            reply_markup=build_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_OTP
    else:
        await update.message.reply_text(
            msg,
            reply_markup=build_add_account_menu()
        )
        return MAIN_MENU


async def handle_otp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle OTP code input."""
    otp = update.message.text.strip()
    phone = context.user_data.get("phone")
    client = context.user_data.get("otp_client")
    
    if not client or not phone:
        await update.message.reply_text(
            "❌ Session expired. Please start again.",
            reply_markup=build_main_menu()
        )
        return MAIN_MENU
    
    success, result = await account_load.verify_otp(client, phone, otp)
    
    if success:
        # Got session string
        session_str = result
        # Get user info
        try:
            me = await client.get_me()
            user_id = me.id
            username = me.username
        except Exception:
            user_id = None
            username = None
            me = None
        
        # Update profile name
        await account_load.update_account_name(client)
        
        # Save to DB
        save_success, save_msg = await account_load.save_account_to_db(
            session_string=session_str,
            phone=phone,
            user_id=user_id,
            username=username,
            added_by=update.effective_user.id,
            source="phone_otp"
        )
        
        await client.disconnect()
        
        await update.message.reply_text(
            f"✅ **Account Added!**\n\n{save_msg}",
            reply_markup=build_main_menu(),
            parse_mode=ParseMode.MARKDOWN
        )
        return MAIN_MENU
    
    elif result == "2FA_REQUIRED":
        context.user_data["2fa_phone"] = phone
        await update.message.reply_text(
            "🔐 **Two-Factor Authentication Required**\n\n"
            "This account has 2FA enabled. Please enter your password:",
            reply_markup=build_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_2FA
    
    else:
        await update.message.reply_text(
            result + "\n\nTry again or send /cancel to abort.",
            reply_markup=build_cancel_keyboard()
        )
        return WAITING_OTP


async def handle_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle 2FA password input."""
    password = update.message.text.strip()
    phone = context.user_data.get("phone")
    client = context.user_data.get("otp_client")
    
    if not client:
        await update.message.reply_text(
            "❌ Session expired. Please start again.",
            reply_markup=build_main_menu()
        )
        return MAIN_MENU
    
    success, result = await account_load.verify_2fa(client, password)
    
    if success:
        session_str = result
        try:
            me = await client.get_me()
            user_id = me.id
            username = me.username
        except Exception:
            user_id = None
            username = None
        
        await account_load.update_account_name(client)
        
        save_success, save_msg = await account_load.save_account_to_db(
            session_string=session_str,
            phone=phone,
            user_id=user_id,
            username=username,
            added_by=update.effective_user.id,
            source="phone_otp"
        )
        
        await client.disconnect()
        
        await update.message.reply_text(
            f"✅ **Account Added!**\n\n{save_msg}",
            reply_markup=build_main_menu(),
            parse_mode=ParseMode.MARKDOWN
        )
        return MAIN_MENU
    else:
        await update.message.reply_text(
            result + "\n\nTry again or send /cancel to abort.",
            reply_markup=build_cancel_keyboard()
        )
        return WAITING_2FA


async def handle_session_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle session file upload."""
    # Check if it's a file
    document = update.message.document
    if not document:
        await update.message.reply_text(
            "❌ Please upload a `.txt` file.",
            reply_markup=build_cancel_keyboard()
        )
        return WAITING_SESSION_FILE
    
    # Download and read file
    try:
        file = await document.get_file()
        content = await file.download_as_bytearray()
        content_str = content.decode("utf-8")
    except Exception as e:
        await update.message.reply_text(
            f"❌ Failed to read file: {str(e)}",
            reply_markup=build_cancel_keyboard()
        )
        return WAITING_SESSION_FILE
    
    # Parse session strings
    accounts = account_load.parse_session_file(content_str)
    
    if not accounts:
        await update.message.reply_text(
            "❌ No valid session strings found in the file.\n\n"
            "Expected format:\n"
            "```\n"
            "Phone: +XXXXXXXXXXXX | Format: TELETHON\n"
            "<session_string>\n"
            "```",
            reply_markup=build_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_SESSION_FILE
    
    await update.message.reply_text(
        f"📄 Found `{len(accounts)}` session(s) in file. Validating...",
        parse_mode=ParseMode.MARKDOWN
    )
    
    added = 0
    failed = 0
    errors = []
    
    for acc in accounts:
        session_str = acc["session_string"]
        phone = acc.get("phone")
        
        # Validate the session
        is_valid, msg, user_info = await account_load.validate_session_string(session_str)
        
        if is_valid:
            # Save to DB
            save_success, save_msg = await account_load.save_account_to_db(
                session_string=session_str,
                phone=phone or user_info.get("phone"),
                user_id=user_info.get("user_id"),
                username=user_info.get("username"),
                added_by=update.effective_user.id,
                source="session_file"
            )
            
            if save_success:
                added += 1
            else:
                failed += 1
                errors.append(save_msg)
        else:
            failed += 1
            errors.append(f"{phone or 'Unknown'}: {msg}")
    
    # Report results
    result_text = (
        f"📄 **Session File Import Complete**\n\n"
        f"✅ Added: `{added}`\n"
        f"❌ Failed/Skipped: `{failed}`\n"
    )
    
    if errors:
        result_text += "\n**Errors:**\n"
        for err in errors[:5]:
            result_text += f"• {err}\n"
        if len(errors) > 5:
            result_text += f"• ... and {len(errors) - 5} more\n"
    
    await update.message.reply_text(
        result_text,
        reply_markup=build_main_menu(),
        parse_mode=ParseMode.MARKDOWN
    )
    return MAIN_MENU


async def handle_tdata_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle TData zip file upload."""
    document = update.message.document
    if not document:
        await update.message.reply_text(
            "❌ Please upload a ZIP file containing the tdata folder.",
            reply_markup=build_cancel_keyboard()
        )
        return WAITING_TDATA_FILE
    
    # Download file
    try:
        file = await document.get_file()
        zip_path = f"temp_tdata_{update.effective_user.id}.zip"
        await file.download_to_drive(zip_path)
    except Exception as e:
        await update.message.reply_text(
            f"❌ Failed to download file: {str(e)}",
            reply_markup=build_cancel_keyboard()
        )
        return WAITING_TDATA_FILE
    
    await update.message.reply_text(
        "🔄 Processing TData folder... This may take a moment.",
        reply_markup=build_cancel_keyboard()
    )
    
    success, msg, session_str = await account_load.add_account_via_tdata(
        zip_path, added_by=update.effective_user.id
    )
    
    # Cleanup temp file
    try:
        os.remove(zip_path)
    except Exception:
        pass
    
    await update.message.reply_text(
        msg,
        reply_markup=build_main_menu(),
        parse_mode=ParseMode.MARKDOWN
    )
    return MAIN_MENU
  # ============================================================
# MESSAGE HANDLERS - JOIN
# ============================================================
async def handle_join_target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle join target input."""
    target = update.message.text.strip()
    context.user_data["join_target"] = target
    
    await update.message.reply_text(
        "⏱ **Join Delay Settings**\n\n"
        "Enter the **minimum** delay (in seconds) between joins:\n\n"
        "Example: `8`",
        reply_markup=build_cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    return WAITING_JOIN_DELAY_MIN


async def handle_join_delay_min(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle minimum delay input."""
    try:
        min_delay = float(update.message.text.strip())
        if min_delay < 1:
            raise ValueError
        context.user_data["join_delay_min"] = min_delay
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid number. Please enter a positive number (e.g., `8`).",
            reply_markup=build_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_JOIN_DELAY_MIN
    
    await update.message.reply_text(
        "⏱ **Maximum Delay**\n\n"
        "Enter the **maximum** delay (in seconds) between joins:\n\n"
        f"Example: `10` (range: {min_delay} to ?)",
        reply_markup=build_cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    return WAITING_JOIN_DELAY_MAX


async def handle_join_delay_max(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle maximum delay input and start join operation."""
    try:
        max_delay = float(update.message.text.strip())
        if max_delay < context.user_data.get("join_delay_min", 1):
            await update.message.reply_text(
                "❌ Maximum delay must be greater than or equal to minimum delay.",
                reply_markup=build_cancel_keyboard()
            )
            return WAITING_JOIN_DELAY_MAX
        context.user_data["join_delay_max"] = max_delay
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid number. Please enter a valid number.",
            reply_markup=build_cancel_keyboard()
        )
        return WAITING_JOIN_DELAY_MAX
    
    target = context.user_data.get("join_target", "")
    min_delay = context.user_data["join_delay_min"]
    max_delay = context.user_data["join_delay_max"]
    
    # Confirm
    target_type, target_id = account_join.parse_target(target)
    type_label = "Public" if target_type == "public" else "Private" if target_type == "private" else "Unknown"
    
    confirm_text = (
        "🔗 **Join Confirmation**\n\n"
        f"**Target:** `{target}` ({type_label})\n"
        f"**Delay Range:** `{min_delay}s` — `{max_delay}s`\n"
        f"**Join Modes:**\n"
        f"  • Always Online: `{config.JOIN_MODE_1_PERCENT}%`\n"
        f"  • Last Seen Recently: `{config.JOIN_MODE_2_PERCENT}%`\n"
        f"  • Offline after 2min: `{config.JOIN_MODE_3_PERCENT}%`\n\n"
        f"Proceed?"
    )
    
    keyboard = [
        [InlineKeyboardButton("✅ Start Join", callback_data="confirm_join")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_op")],
    ]
    
    await update.message.reply_text(
        confirm_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )
    return WAITING_CONFIRM


async def handle_confirm_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Execute the join operation after confirmation."""
    query = update.callback_query
    await query.answer()
    
    if query.data != "confirm_join":
        return MAIN_MENU
    
    target = context.user_data.get("join_target", "")
    min_delay = context.user_data.get("join_delay_min", 5)
    max_delay = context.user_data.get("join_delay_max", 10)
    
    global cancel_event
    cancel_event = asyncio.Event()
    
    await query.edit_message_text(
        "🔗 **Join Operation Started**\n\n"
        f"Target: `{target}`\n"
        f"Delay: `{min_delay}s` - `{max_delay}s`\n\n"
        "Progress will be updated below..."
        "\n\nUse `/cancel` to stop.",
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Progress tracker
    last_msg = None
    
    async def progress_callback(status: str, percent: int):
        nonlocal last_msg
        try:
            if last_msg is None:
                msg = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"🔗 **Join Progress**\n\n{status}"
                )
                last_msg = msg
            else:
                await last_msg.edit_text(
                    f"🔗 **Join Progress** `{percent}%`\n\n{status}"
                )
        except Exception:
            pass
    
    results = await account_join.execute_join(
        target=target,
        min_delay=min_delay,
        max_delay=max_delay,
        progress_callback=progress_callback,
        cancel_event=cancel_event
    )
    
    # Final report
    if cancel_event.is_set():
        header = "⛔ **Join Cancelled**\n\n"
    else:
        header = "✅ **Join Complete**\n\n"
    
    mode_details = (
        f"🟢 Always Online: `{results.get('mode_1_count', 0)}`\n"
        f"🔵 Last Seen Recently: `{results.get('mode_2_count', 0)}`\n"
        f"⚪ Offline after 2min: `{results.get('mode_3_count', 0)}`\n"
    )
    
    report = (
        f"{header}"
        f"**Target:** `{target}`\n\n"
        f"📊 **Results:**\n"
        f"✅ Success: `{results['success']}`\n"
        f"❌ Failed: `{results['failed']}`\n"
        f"📦 Total: `{results['total']}`\n\n"
        f"**Mode Distribution:**\n{mode_details}\n"
        f"⏱ _Delay range: {min_delay}s - {max_delay}s_"
    )
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=report,
        reply_markup=build_main_menu(),
        parse_mode=ParseMode.MARKDOWN
    )
    
    if last_msg:
        try:
            await last_msg.delete()
        except Exception:
            pass
    
    return MAIN_MENU
  # ============================================================
# MESSAGE HANDLERS - VIEWS
# ============================================================
async def handle_views_links(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle view boost links input."""
    text = update.message.text.strip()
    links = [line.strip() for line in text.split("\n") if line.strip()]
    
    # Validate links
    valid_links = []
    for link in links:
        channel_id, msg_id = views_module.parse_post_link(link)
        if channel_id is not None and msg_id is not None:
            valid_links.append(link)
    
    if not valid_links:
        await update.message.reply_text(
            "❌ No valid post links found.\n\n"
            "Format: `t.me/username/1234` or `t.me/c/123456/1234`",
            reply_markup=build_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_VIEWS_LINKS
    
    context.user_data["views_links"] = valid_links
    
    await update.message.reply_text(
        f"👁 **View Boost**\n\n"
        f"Found `{len(valid_links)}` valid link(s).\n\n"
        f"How many total views would you like to add?\n"
        f"(Distributed across all accounts)\n\n"
        f"Enter a number (e.g., `100`):",
        reply_markup=build_cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    return WAITING_VIEWS_COUNT


async def handle_views_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle views count and execute view boosting."""
    try:
        count = int(update.message.text.strip())
        if count < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid number. Please enter a positive integer.",
            reply_markup=build_cancel_keyboard()
        )
        return WAITING_VIEWS_COUNT
    
    links = context.user_data.get("views_links", [])
    
    global cancel_event
    cancel_event = asyncio.Event()
    
    await update.message.reply_text(
        f"👁 **View Boost Started**\n\n"
        f"Links: `{len(links)}`\n"
        f"Target Views: `{count}`\n\n"
        f"Use `/cancel` to stop.",
        parse_mode=ParseMode.MARKDOWN
    )
    
    last_msg = None
    
    async def progress_callback(status: str, percent: int):
        nonlocal last_msg
        try:
            if last_msg is None:
                msg = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"👁 **View Boost** `{percent}%`\n\n{status}"
                )
                last_msg = msg
            else:
                await last_msg.edit_text(
                    f"👁 **View Boost** `{percent}%`\n\n{status}"
                )
        except Exception:
            pass
    
    results = await views_module.boost_views(
        links=links,
        total_views_desired=count,
        progress_callback=progress_callback,
        cancel_event=cancel_event
    )
    
    header = "⛔ **Cancelled**\n\n" if cancel_event.is_set() else "✅ **View Boost Complete**\n\n"
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            f"{header}"
            f"📊 Results:\n"
            f"📎 Links: `{results['total_links']}`\n"
            f"👥 Accounts: `{results['total_accounts']}`\n"
            f"🎯 Requested: `{results['views_requested']}`\n"
            f"✅ Achieved: `{results['views_achieved']}`\n"
            f"✔ Success: `{results['success']}`\n"
            f"✖ Failed: `{results['failed']}`"
        ),
        reply_markup=build_main_menu(),
        parse_mode=ParseMode.MARKDOWN
    )
    
    if last_msg:
        try:
            await last_msg.delete()
        except Exception:
            pass
    
    return MAIN_MENU


# ============================================================
# MESSAGE HANDLERS - REACTIONS
# ============================================================
async def handle_reaction_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle reaction post link input."""
    link = update.message.text.strip()
    
    channel_id, msg_id = views_module.parse_post_link(link)
    if channel_id is None or msg_id is None:
        await update.message.reply_text(
            "❌ Invalid post link.\n\n"
            "Format: `t.me/username/1234` or `t.me/c/123456/1234`",
            reply_markup=build_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_REACTION_LINK
    
    context.user_data["reaction_link"] = link
    
    await update.message.reply_text(
        "💜 **Reaction Types**\n\n"
        "Enter the reactions you want to use (separated by spaces):\n\n"
        "Example: `❤️ 👍 🔥 😂 🎉`\n\n"
        "Supported: ❤️ 👍 🔥 😂 🎉 😊 ☺️ 🥰 😍 🤩 🤗 ❣️ 💔 🫶\n\n"
        "For mixed reactions, just list multiple emojis!",
        reply_markup=build_cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    return WAITING_REACTION_TYPES


async def handle_reaction_types(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle reaction types input."""
    text = update.message.text.strip()
    
    # Extract emojis from the text
    import emoji as emoji_lib
    reactions = [c for c in text if c in (
        '❤️', '👍', '🔥', '😂', '🎉', '😊', '☺️', '🥰', '😍', 
        '🤩', '🤗', '❣️', '💔', '🫶', '❤', '💜', '💙', '💚', '💛', '🧡', '🤍', '🤎',
        '🖤', '❤️‍🔥', '❤️‍🩹', '😢', '😭', '😤', '😡', '🥱', '😴',
        '🇺🇳', '💯', '👌', '🤌', '🫡', '🫠', '🫣', '🫤', '🪿'
    )]
    
    if not reactions:
        # Fallback: try to find any emoji
        try:
            import emoji as emoji_lib
            reactions = [c for c in text if emoji_lib.is_emoji(c)]
        except ImportError:
            reactions = list(text.strip())[:10]
    
    if not reactions:
        await update.message.reply_text(
            "❌ No valid emoji reactions found. Please send emoji(s) like: `❤️ 👍 🔥`",
            reply_markup=build_cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_REACTION_TYPES
    
    context.user_data["reaction_types"] = reactions[:5]  # Max 5 unique types
    
    await update.message.reply_text(
        f"💜 **Reactions Selected:** {' '.join(reactions[:5])}\n\n"
        f"How many accounts should react? (Max 1 per account)\n\n"
        f"Enter a number:",
        reply_markup=build_cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    return WAITING_REACTION_COUNT


async def handle_reaction_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle reaction count and execute."""
    try:
        count = int(update.message.text.strip())
        if count < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid number. Enter a positive integer.",
            reply_markup=build_cancel_keyboard()
        )
        return WAITING_REACTION_COUNT
    
    link = context.user_data.get("reaction_link", "")
    reactions = context.user_data.get("reaction_types", ["❤️"])
    
    global cancel_event
    cancel_event = asyncio.Event()
    
    await update.message.reply_text(
        f"💜 **Reaction Operation Started**\n\n"
        f"Link: `{link}`\n"
        f"Reactions: {' '.join(reactions)}\n"
        f"Target: `{count}` reactions\n\n"
        f"Use `/cancel` to stop.",
        parse_mode=ParseMode.MARKDOWN
    )
    
    last_msg = None
    
    async def progress_callback(status: str, percent: int):
        nonlocal last_msg
        try:
            if last_msg is None:
                msg = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"💜 **Reactions** `{percent}%`\n\n{status}"
                )
                last_msg = msg
            else:
                await last_msg.edit_text(
                    f"💜 **Reactions** `{percent}%`\n\n{status}"
                )
        except Exception:
            pass
    
    results = await reaction_module.send_reactions(
        link=link,
        reactions=reactions,
        total_reactions_desired=count,
        progress_callback=progress_callback,
        cancel_event=cancel_event
    )
    
    header = "⛔ **Cancelled**\n\n" if cancel_event.is_set() else "✅ **Reactions Complete**\n\n"
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            f"{header}"
            f"📊 Results:\n"
            f"📎 Link: `{results['link']}`\n"
            f"💜 Reactions: {' '.join(results['reactions_available'])}\n"
            f"🎯 Requested: `{results['total_requested']}`\n"
            f"✅ Sent: `{results['total_sent']}`\n"
            f"✔ Success: `{results['success']}`\n"
            f"✖ Failed: `{results['failed']}`"
        ),
        reply_markup=build_main_menu(),
        parse_mode=ParseMode.MARKDOWN
    )
    
    if last_msg:
        try:
            await last_msg.delete()
        except Exception:
            pass
    
    return MAIN_MENU
  # ============================================================
# ERROR HANDLER
# ============================================================
async def error_handler(update: Optional[Update], context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors in the bot."""
    logger.error(f"Exception while handling update: {context.error}", exc_info=True)
    
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ **An unexpected error occurred.**\n\n"
                "The operation has been cancelled. Please try again.\n"
                "If the issue persists, check the logs.",
                reply_markup=build_main_menu(),
                parse_mode=ParseMode.MARKDOWN
            )
    except Exception:
        pass


# ============================================================
# FALLBACK HANDLER
# ============================================================
async def fallback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle unexpected messages."""
    await update.message.reply_text(
        "❓ Unexpected input.\n\n"
        "Use the menu buttons or type `/cancel` to return to the main menu.",
        reply_markup=build_main_menu()
    )
    return MAIN_MENU


# ============================================================
# MAIN
# ============================================================
def main() -> None:
    """Start the bot."""
    # Connect to MongoDB
    if not db.connect():
        logger.error("Failed to connect to MongoDB. Exiting.")
        sys.exit(1)
    
    # Create the Application
    application = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )
    
    # Set bot commands
    async def set_commands(app):
        await app.bot.set_my_commands([
            BotCommand("start", "Open the main menu"),
            BotCommand("cancel", "Cancel current operation"),
            BotCommand("help", "Show help information"),
            BotCommand("stats", "Show account statistics"),
        ])
    
    application.post_init = set_commands
    
    # --- Conversation Handler ---
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("help", help_command),
            CommandHandler("stats", stats_command),
            CallbackQueryHandler(button_handler, pattern="^(?!confirm_join)"),
        ],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(button_handler),
                CommandHandler("start", start),
                CommandHandler("help", help_command),
                CommandHandler("stats", stats_command),
            ],
            WAITING_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_phone),
                CommandHandler("cancel", cancel_command),
                CallbackQueryHandler(button_handler),
            ],
            WAITING_OTP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_otp),
                CommandHandler("cancel", cancel_command),
                CallbackQueryHandler(button_handler),
            ],
            WAITING_2FA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_2fa),
                CommandHandler("cancel", cancel_command),
                CallbackQueryHandler(button_handler),
            ],
            WAITING_SESSION_FILE: [
                MessageHandler(filters.Document.ALL, handle_session_file),
                CommandHandler("cancel", cancel_command),
                CallbackQueryHandler(button_handler),
            ],
            WAITING_TDATA_FILE: [
                MessageHandler(filters.Document.ALL, handle_tdata_file),
                CommandHandler("cancel", cancel_command),
                CallbackQueryHandler(button_handler),
            ],
            WAITING_JOIN_TARGET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_join_target),
                CommandHandler("cancel", cancel_command),
                CallbackQueryHandler(button_handler),
            ],
            WAITING_JOIN_DELAY_MIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_join_delay_min),
                CommandHandler("cancel", cancel_command),
                CallbackQueryHandler(button_handler),
            ],
            WAITING_JOIN_DELAY_MAX: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_join_delay_max),
                CommandHandler("cancel", cancel_command),
                CallbackQueryHandler(button_handler),
            ],
            WAITING_VIEWS_LINKS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_views_links),
                CommandHandler("cancel", cancel_command),
                CallbackQueryHandler(button_handler),
            ],
            WAITING_VIEWS_COUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_views_count),
                CommandHandler("cancel", cancel_command),
                CallbackQueryHandler(button_handler),
            ],
            WAITING_REACTION_LINK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reaction_link),
                CommandHandler("cancel", cancel_command),
                CallbackQueryHandler(button_handler),
            ],
            WAITING_REACTION_TYPES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reaction_types),
                CommandHandler("cancel", cancel_command),
                CallbackQueryHandler(button_handler),
            ],
            WAITING_REACTION_COUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reaction_count),
                CommandHandler("cancel", cancel_command),
                CallbackQueryHandler(button_handler),
            ],
            WAITING_CONFIRM: [
                CallbackQueryHandler(handle_confirm_join, pattern="^confirm_join$"),
                CallbackQueryHandler(button_handler, pattern="^cancel_op$"),
                CommandHandler("cancel", cancel_command),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            CommandHandler("start", start),
            MessageHandler(filters.ALL, fallback_handler),
        ],
        allow_reentry=True,
        per_chat=True,
        per_user=True,
    )
    
    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)
    
    # Start the bot
    logger.info("🤖 Bot is starting...")
    print("=" * 50)
    print("  🤖 Telegram Account Manager Bot")
    print("  ✨ Premium Account Suite")
    print("=" * 50)
    print(f"  Owner ID: {config.OWNER_ID}")
    print(f"  Admins: {len(config.ADMIN_IDS)}")
    print(f"  MongoDB: {'✅ Connected' if db.db else '❌ Disconnected'}")
    print(f"  Bot: @{config.BOT_TOKEN.split(':')[0]}")
    print("=" * 50)
    print("  Bot is running. Press Ctrl+C to stop.")
    print("=" * 50)
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

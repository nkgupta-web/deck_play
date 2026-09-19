import asyncio
import math
from typing import Optional, Tuple
from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import config
import database
from game_state import GAMES

admin_router = Router()

STAT_KEYS_DISPLAY = [
    ("games", "🎮 Games"),
    ("wins", "🏆 Wins"),
    ("joint_wins", "🤝 Joint Wins"),
    ("rounds_survived", "❤️ Survived"),
    ("exact_31", "🎯 Exact 31"),
    ("exact_30_5", "⭐ 30.5"),
    ("best_streak", "🔥 Best Streak"),
    ("ex_1", "🔄 Exchanges"),
    ("passes", "⏭️ Passes"),
    ("lives_lost", "💀 Lives Lost")
]

class StatEditStates(StatesGroup):
    waiting_for_single_value = State()
    waiting_for_wizard_value = State()
    waiting_for_announcement = State()

async def resolve_target_user(bot: Bot, message: Message, command_args: str) -> Optional[Tuple[int, str, str]]:
    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        username = f"@{u.username}" if u.username else "None"
        return u.id, u.full_name, username

    arg = command_args.strip()
    if not arg:
        return None

    if arg.isdigit() or (arg.startswith("-") and arg[1:].isdigit()):
        uid = int(arg)
        stats = database.get_user_stats(uid)
        name = stats.get("name", "Unknown") if stats else "Unknown"
        return uid, name, "N/A"

    if arg.startswith("@"):
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, name FROM call31_stats WHERE LOWER(name) LIKE %s LIMIT 1;", (f"%{arg[1:].lower()}%",))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row:
            return row[0], row[1], arg
    return None

def build_setstats_markup(target_id: int, admin_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="🎮 Games", callback_data=f"adm_s:games:{target_id}:{admin_id}"),
            InlineKeyboardButton(text="🏆 Wins", callback_data=f"adm_s:wins:{target_id}:{admin_id}")
        ],
        [
            InlineKeyboardButton(text="🤝 Joint Wins", callback_data=f"adm_s:joint_wins:{target_id}:{admin_id}"),
            InlineKeyboardButton(text="❤️ Survived", callback_data=f"adm_s:rounds_survived:{target_id}:{admin_id}")
        ],
        [
            InlineKeyboardButton(text="🎯 Exact 31", callback_data=f"adm_s:exact_31:{target_id}:{admin_id}"),
            InlineKeyboardButton(text="⭐ 30.5", callback_data=f"adm_s:exact_30_5:{target_id}:{admin_id}")
        ],
        [
            InlineKeyboardButton(text="🔥 Best Streak", callback_data=f"adm_s:best_streak:{target_id}:{admin_id}"),
            InlineKeyboardButton(text="🔄 Exchanges", callback_data=f"adm_s:ex_1:{target_id}:{admin_id}")
        ],
        [
            InlineKeyboardButton(text="⏭️ Passes", callback_data=f"adm_s:passes:{target_id}:{admin_id}"),
            InlineKeyboardButton(text="💀 Lives Lost", callback_data=f"adm_s:lives_lost:{target_id}:{admin_id}")
        ],
        [
            InlineKeyboardButton(text="✏️ Set All Stats", callback_data=f"adm_w_start:{target_id}:{admin_id}")
        ],
        [
            InlineKeyboardButton(text="🔄 Reset All Stats", callback_data=f"adm_rst_ask:{target_id}:{admin_id}")
        ],
        [
            InlineKeyboardButton(text="❌ Cancel", callback_data=f"adm_cancel:{admin_id}")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def render_setstats_panel(user_id: int, name: str, username: str, stats: dict) -> str:
    return (
        "⚙️ <b>SET PLAYER STATS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "👤 <b>PLAYER</b>\n"
        f"• Name : <b>{name}</b>\n"
        f"• User : {username}\n"
        f"• ID   : <code>{user_id}</code>\n\n"
        "🎴 <b>CALL 31 STATS</b>\n\n"
        f"🎮 Games       : {stats.get('games', 0)}\n"
        f"🏆 Wins        : {stats.get('wins', 0)}\n"
        f"🤝 Joint Wins  : {stats.get('joint_wins', 0)}\n"
        f"❤️ Survived    : {stats.get('rounds_survived', 0)}\n"
        f"🎯 Exact 31    : {stats.get('exact_31', 0)}\n"
        f"⭐ 30.5        : {stats.get('exact_30_5', 0)}\n"
        f"🔥 Best Streak : {stats.get('best_streak', 0)}\n"
        f"🔄 Exchanges   : {stats.get('ex_1', 0)}\n"
        f"⏭️ Passes      : {stats.get('passes', 0)}\n"
        f"💀 Lives Lost  : {stats.get('lives_lost', 0)}\n\n"
        "<i>Select a stat to edit:</i>"
    )

# ━━━━━━━━━━━━━━━━━━━━
# 1. OWNER ONLY COMMANDS
# ━━━━━━━━━━━━━━━━━━━━

@admin_router.message(Command("addadmin"))
async def cmd_addadmin(message: Message, bot: Bot):
    if not database.is_owner(message.from_user.id):
        return

    target = await resolve_target_user(bot, message, message.text.replace("/addadmin", ""))
    if not target:
        await message.reply("⚠️ Usage: <code>/addadmin &lt;user_id/@username&gt;</code> or reply to a message.")
        return

    uid, name, uname = target
    database.add_admin(uid, uname, message.from_user.id)
    database.log_admin_action(message.from_user.id, message.from_user.full_name, "ADD_ADMIN", str(uid), "None", "ADMIN")
    await message.reply(
        "🛡️ <b>ADMIN ADDED</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>User:</b> {name} ({uname})\n"
        f"🆔 <b>ID:</b> <code>{uid}</code>\n"
        "🟢 Granted operational admin access."
    )

@admin_router.message(Command("removeadmin"))
async def cmd_removeadmin(message: Message, bot: Bot):
    if not database.is_owner(message.from_user.id):
        return

    target = await resolve_target_user(bot, message, message.text.replace("/removeadmin", ""))
    if not target:
        await message.reply("⚠️ Usage: <code>/removeadmin &lt;user_id/@username&gt;</code> or reply to a message.")
        return

    uid, name, uname = target
    if uid == config.OWNER_ID:
        await message.reply("❌ Cannot remove the bot Owner.")
        return

    deleted = database.remove_admin(uid)
    if deleted:
        database.log_admin_action(message.from_user.id, message.from_user.full_name, "REMOVE_ADMIN", str(uid), "ADMIN", "None")
        await message.reply(f"🛡️ Admin access revoked for <code>{uid}</code>.")
    else:
        await message.reply("❌ User is not an admin.")

@admin_router.message(Command("admins"))
async def cmd_admins(message: Message):
    if not database.is_owner(message.from_user.id):
        return

    admins = database.get_all_admins()
    lines = [
        "👑 <b>DECK PLAY ADMIN DIRECTORY</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n",
        f"👑 <b>Owner:</b> <code>{config.OWNER_ID}</code>\n"
    ]
    if not admins:
        lines.append("<i>No secondary admins assigned.</i>")
    else:
        for idx, adm in enumerate(admins, 1):
            lines.append(f"{idx}. <b>ID:</b> <code>{adm['user_id']}</code> | {adm.get('username', 'N/A')}")

    await message.reply("\n".join(lines))

@admin_router.message(Command("maintenance"))
async def cmd_maintenance(message: Message):
    if not database.is_owner(message.from_user.id):
        return

    status = database.get_maintenance_status()
    st_text = "🔴 MAINTENANCE" if status else "🟢 ONLINE"
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Enable Maintenance", callback_data=f"adm_maint:on:{message.from_user.id}")],
        [InlineKeyboardButton(text="🟢 Disable Maintenance", callback_data=f"adm_maint:off:{message.from_user.id}")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data=f"adm_cancel:{message.from_user.id}")]
    ])
    await message.reply(
        "⚙️ <b>DECK PLAY MAINTENANCE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Current Status: <b>{st_text}</b>\n\n"
        "<i>When enabled, new Call 31 matches cannot be initiated.</i>",
        reply_markup=markup
    )

@admin_router.callback_query(F.data.startswith("adm_maint:"))
async def cb_maintenance_toggle(callback: CallbackQuery):
    parts = callback.data.split(":")
    action = parts[1]
    admin_id = int(parts[2])

    if callback.from_user.id != admin_id or not database.is_owner(callback.from_user.id):
        await callback.answer("🔒 Unauthorized.", show_alert=True)
        return

    is_on = (action == "on")
    database.set_maintenance_status(is_on)
    database.log_admin_action(callback.from_user.id, callback.from_user.full_name, "MAINTENANCE", "SYSTEM", str(not is_on), str(is_on))

    if is_on:
        await callback.message.edit_text(
            "⚙️ <b>DECK PLAY MAINTENANCE</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🔴 <b>MAINTENANCE MODE ENABLED</b>\n\n"
            "New Call 31 matches cannot be started. Active matches will continue normally."
        )
    else:
        await callback.message.edit_text(
            "⚙️ <b>DECK PLAY MAINTENANCE</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🟢 <b>MAINTENANCE MODE DISABLED</b>\n\n"
            "Call 31 arenas are now open."
        )
    await callback.answer()

@admin_router.message(Command("setstats"))
async def cmd_setstats(message: Message, bot: Bot):
    if not database.is_owner(message.from_user.id):
        return

    target = await resolve_target_user(bot, message, message.text.replace("/setstats", ""))
    if not target:
        await message.reply("⚠️ Usage: <code>/setstats &lt;user_id/@username&gt;</code> or reply to a player's message.")
        return

    uid, name, uname = target
    stats = database.get_user_stats(uid)
    if not stats:
        await message.reply("❌ Player has no existing Call 31 records in the database.")
        return

    text = render_setstats_panel(uid, name, uname, stats)
    markup = build_setstats_markup(uid, message.from_user.id)
    await message.reply(text, reply_markup=markup)

@admin_router.message(Command("resetstats"))
async def cmd_resetstats(message: Message, bot: Bot):
    if not database.is_owner(message.from_user.id):
        return

    target = await resolve_target_user(bot, message, message.text.replace("/resetstats", ""))
    if not target:
        await message.reply("⚠️ Usage: <code>/resetstats &lt;user_id/@username&gt;</code> or reply to a message.")
        return

    uid, name, _ = target
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚠️ RESET STATS", callback_data=f"adm_rst_do:{uid}:{message.from_user.id}"),
            InlineKeyboardButton(text="❌ CANCEL", callback_data=f"adm_cancel:{message.from_user.id}")
        ]
    ])
    await message.reply(
        "⚠️ <b>RESET PLAYER STATS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Player : <b>{name}</b>\n"
        f"🆔 ID     : <code>{uid}</code>\n\n"
        "This will reset the player's Call 31 statistics. Account will remain active.",
        reply_markup=markup
    )

@admin_router.callback_query(F.data.startswith("adm_rst_ask:"))
async def cb_reset_ask(callback: CallbackQuery):
    parts = callback.data.split(":")
    target_id = int(parts[1])
    admin_id = int(parts[2])

    if callback.from_user.id != admin_id or not database.is_owner(callback.from_user.id):
        await callback.answer("🔒 Unauthorized.", show_alert=True)
        return

    stats = database.get_user_stats(target_id)
    name = stats.get("name", "Player") if stats else "Player"
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚠️ RESET STATS", callback_data=f"adm_rst_do:{target_id}:{admin_id}"),
            InlineKeyboardButton(text="❌ CANCEL", callback_data=f"adm_cancel:{admin_id}")
        ]
    ])
    await callback.message.edit_text(
        "⚠️ <b>RESET PLAYER STATS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Player : <b>{name}</b>\n"
        f"🆔 ID     : <code>{target_id}</code>\n\n"
        "This will reset the player's Call 31 statistics.",
        reply_markup=markup
    )

@admin_router.callback_query(F.data.startswith("adm_rst_do:"))
async def cb_reset_perform(callback: CallbackQuery):
    parts = callback.data.split(":")
    target_id = int(parts[1])
    admin_id = int(parts[2])

    if callback.from_user.id != admin_id or not database.is_owner(callback.from_user.id):
        await callback.answer("🔒 Unauthorized.", show_alert=True)
        return

    stats = database.get_user_stats(target_id)
    name = stats.get("name", "Player") if stats else "Player"
    database.reset_player_stats(target_id)
    database.log_admin_action(callback.from_user.id, callback.from_user.full_name, "RESET_STATS", f"{name} ({target_id})", "ALL_STATS", "0")

    await callback.message.edit_text(
        "✅ <b>STATS RESET</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Player : <b>{name}</b>\n\n"
        "All Call 31 statistics have been reset."
    )
    await callback.answer()

# ━━━━━━━━━━━━━━━━━━━━
# 2. INDIVIDUAL STAT EDIT
# ━━━━━━━━━━━━━━━━━━━━

@admin_router.callback_query(F.data.startswith("adm_s:"))
async def cb_edit_single_stat(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    stat_key = parts[1]
    target_id = int(parts[2])
    admin_id = int(parts[3])

    if callback.from_user.id != admin_id or not database.is_owner(callback.from_user.id):
        await callback.answer("🔒 Unauthorized.", show_alert=True)
        return

    stats = database.get_user_stats(target_id)
    if not stats:
        await callback.answer("Player record not found.", show_alert=True)
        return

    stat_name = dict(STAT_KEYS_DISPLAY).get(stat_key, stat_key)
    curr_val = stats.get(stat_key, 0)

    await state.update_data(
        target_id=target_id,
        admin_id=admin_id,
        stat_key=stat_key,
        stat_name=stat_name,
        curr_val=curr_val,
        name=stats.get("name", "Player")
    )
    await state.set_state(StatEditStates.waiting_for_single_value)

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data=f"adm_cancel:{admin_id}")]
    ])

    await callback.message.edit_text(
        "✏️ <b>EDIT STAT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Player : <b>{stats.get('name', 'Player')}</b>\n\n"
        f"<b>{stat_name}</b>\n"
        f"Current Value: <b>{curr_val}</b>\n\n"
        "Send the new value:\n",
        reply_markup=markup
    )
    await callback.answer()

@admin_router.message(StatEditStates.waiting_for_single_value)
async def process_single_stat_input(message: Message, state: FSMContext):
    data = await state.get_data()
    if message.from_user.id != data.get("admin_id"):
        return

    val_text = message.text.strip()
    if not val_text.isdigit():
        await message.reply("❌ Invalid value. Please enter a valid non-negative number.")
        return

    new_val = int(val_text)
    await state.update_data(new_val=new_val)

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Confirm", callback_data=f"adm_single_confirm:{data['admin_id']}"),
            InlineKeyboardButton(text="❌ Cancel", callback_data=f"adm_cancel:{data['admin_id']}")
        ]
    ])

    await message.reply(
        "⚠️ <b>CONFIRM STAT CHANGE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Player : <b>{data['name']}</b>\n\n"
        f"<b>{data['stat_name']}</b>\n"
        f"<b>{data['curr_val']}</b> → <b>{new_val}</b>",
        reply_markup=markup
    )

@admin_router.callback_query(F.data.startswith("adm_single_confirm:"))
async def cb_confirm_single_stat(callback: CallbackQuery, state: FSMContext):
    admin_id = int(callback.data.split(":")[1])
    if callback.from_user.id != admin_id or not database.is_owner(callback.from_user.id):
        await callback.answer("🔒 Unauthorized.", show_alert=True)
        return

    data = await state.get_data()
    database.set_player_single_stat(data["target_id"], data["stat_key"], data["new_val"])
    database.log_admin_action(
        callback.from_user.id, callback.from_user.full_name,
        "SET_STAT", f"{data['name']} ({data['target_id']})",
        f"{data['stat_key']}:{data['curr_val']}", f"{data['stat_key']}:{data['new_val']}"
    )
    await state.clear()

    stats = database.get_user_stats(data["target_id"])
    text = render_setstats_panel(data["target_id"], data["name"], "N/A", stats)
    markup = build_setstats_markup(data["target_id"], admin_id)

    await callback.message.edit_text(
        "✅ <b>STAT UPDATED</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Player : <b>{data['name']}</b>\n\n"
        f"<b>{data['stat_name']}</b>\n"
        f"<b>{data['curr_val']}</b> → <b>{data['new_val']}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n" + text,
        reply_markup=markup
    )
    await callback.answer()

# ━━━━━━━━━━━━━━━━━━━━
# 3. SET ALL STATS (WIZARD)
# ━━━━━━━━━━━━━━━━━━━━

@admin_router.callback_query(F.data.startswith("adm_w_start:"))
async def cb_wizard_start(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    target_id = int(parts[1])
    admin_id = int(parts[2])

    if callback.from_user.id != admin_id or not database.is_owner(callback.from_user.id):
        await callback.answer("🔒 Unauthorized.", show_alert=True)
        return

    stats = database.get_user_stats(target_id)
    if not stats:
        await callback.answer("Player record not found.", show_alert=True)
        return

    await state.update_data(
        target_id=target_id,
        admin_id=admin_id,
        name=stats.get("name", "Player"),
        wizard_step=0,
        original_stats=stats,
        new_stats_collected={}
    )
    await state.set_state(StatEditStates.waiting_for_wizard_value)

    k, disp = STAT_KEYS_DISPLAY[0]
    curr_v = stats.get(k, 0)

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data=f"adm_cancel:{admin_id}")]
    ])

    await callback.message.edit_text(
        "🎮 <b>SET ALL STATS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Player : <b>{stats.get('name', 'Player')}</b>\n\n"
        "Step 1/10\n\n"
        f"<b>{disp}</b>\n"
        f"Current: <b>{curr_v}</b>\n\n"
        "Send new value:",
        reply_markup=markup
    )
    await callback.answer()

@admin_router.message(StatEditStates.waiting_for_wizard_value)
async def process_wizard_step(message: Message, state: FSMContext):
    data = await state.get_data()
    if message.from_user.id != data.get("admin_id"):
        return

    val_text = message.text.strip()
    if not val_text.isdigit():
        await message.reply("❌ Invalid value. Send a non-negative number.")
        return

    val = int(val_text)
    step = data["wizard_step"]
    stat_key, _ = STAT_KEYS_DISPLAY[step]

    collected = data["new_stats_collected"]
    collected[stat_key] = val

    next_step = step + 1
    if next_step < len(STAT_KEYS_DISPLAY):
        await state.update_data(wizard_step=next_step, new_stats_collected=collected)
        next_k, next_disp = STAT_KEYS_DISPLAY[next_step]
        orig_v = data["original_stats"].get(next_k, 0)

        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data=f"adm_cancel:{data['admin_id']}")]
        ])
        await message.reply(
            "🎮 <b>SET ALL STATS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Player : <b>{data['name']}</b>\n\n"
            f"Step {next_step + 1}/10\n\n"
            f"<b>{next_disp}</b>\n"
            f"Current: <b>{orig_v}</b>\n\n"
            "Send new value:",
            reply_markup=markup
        )
    else:
        await state.update_data(new_stats_collected=collected)
        orig = data["original_stats"]

        lines = [
            "⚠️ <b>CONFIRM ALL STAT CHANGES</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Player : <b>{data['name']}</b>\n"
        ]
        for sk, sdisp in STAT_KEYS_DISPLAY:
            lines.append(f"• {sdisp:<15} : {orig.get(sk, 0)} → <b>{collected[sk]}</b>")

        markup = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ APPLY CHANGES", callback_data=f"adm_w_apply:{data['admin_id']}"),
                InlineKeyboardButton(text="❌ CANCEL", callback_data=f"adm_cancel:{data['admin_id']}")
            ]
        ])
        await message.reply("\n".join(lines), reply_markup=markup)

@admin_router.callback_query(F.data.startswith("adm_w_apply:"))
async def cb_wizard_apply(callback: CallbackQuery, state: FSMContext):
    admin_id = int(callback.data.split(":")[1])
    if callback.from_user.id != admin_id or not database.is_owner(callback.from_user.id):
        await callback.answer("🔒 Unauthorized.", show_alert=True)
        return

    data = await state.get_data()
    database.set_player_all_stats(data["target_id"], data["new_stats_collected"])
    database.log_admin_action(
        callback.from_user.id, callback.from_user.full_name,
        "SET_ALL_STATS", f"{data['name']} ({data['target_id']})",
        "ALL_FIELDS", "UPDATED_10_FIELDS"
    )
    await state.clear()

    await callback.message.edit_text(
        "✅ <b>ALL STATS UPDATED</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Player : <b>{data['name']}</b>\n\n"
        "All 10 Call 31 statistics have been committed to the database."
    )
    await callback.answer()

# ━━━━━━━━━━━━━━━━━━━━
# 4. OWNER + ADMIN COMMANDS
# ━━━━━━━━━━━━━━━━━━━━

@admin_router.message(Command("playerinfo"))
async def cmd_playerinfo(message: Message, bot: Bot):
    if not database.is_admin(message.from_user.id):
        return

    target = await resolve_target_user(bot, message, message.text.replace("/playerinfo", ""))
    if not target:
        await message.reply("⚠️ Usage: <code>/playerinfo &lt;user_id/@username&gt;</code> or reply to a player.")
        return

    uid, name, uname = target
    stats = database.get_user_stats(uid)
    if not stats:
        await message.reply("❌ Player not found in database.")
        return

    games = stats.get("games", 0)
    wins = stats.get("wins", 0)
    wr = f"{(wins / games) * 100:.1f}%" if games > 0 else "0.0%"

    text = (
        "👤 <b>PLAYER INFORMATION</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "👤 <b>PLAYER</b>\n"
        f"• Name   : {stats.get('name', name)}\n"
        f"• User   : {uname}\n"
        f"• ID     : <code>{uid}</code>\n\n"
        "🎴 <b>CALL 31</b>\n\n"
        f"• 🎮 Games       : {games}\n"
        f"• 🏆 Wins        : {wins}\n"
        f"• 🤝 Joint Wins  : {stats.get('joint_wins', 0)}\n"
        f"• ❤️ Survived    : {stats.get('rounds_survived', 0)}\n"
        f"• 🎯 Exact 31    : {stats.get('exact_31', 0)}\n"
        f"• ⭐ 30.5        : {stats.get('exact_30_5', 0)}\n"
        f"• 🔥 Best Streak : {stats.get('best_streak', 0)}\n"
        f"• 🔄 Exchanges   : {stats.get('ex_1', 0)}\n"
        f"• ⏭️ Passes      : {stats.get('passes', 0)}\n"
        f"• 💀 Lives Lost  : {stats.get('lives_lost', 0)}\n\n"
        "📊 <b>PERFORMANCE</b>\n"
        f"• Win Rate : <b>{wr}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )
    await message.reply(text)

@admin_router.message(Command("activematches"))
async def cmd_activematches(message: Message):
    if not database.is_admin(message.from_user.id):
        return
    await render_active_matches_page(message, 1, message.from_user.id)

async def render_active_matches_page(message_or_cb, page: int, admin_id: int):
    active_rooms = [g for g in GAMES.values() if g.status in ("LOBBY", "IN_PROGRESS")]
    total = len(active_rooms)
    per_page = 3
    total_pages = max(1, math.ceil(total / per_page))
    page = min(max(1, page), total_pages)

    start_idx = (page - 1) * per_page
    current_batch = active_rooms[start_idx:start_idx + per_page]

    lines = [
        "🎮 <b>ACTIVE CALL 31 MATCHES</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
    ]
    if not current_batch:
        lines.append("<i>No active matches.</i>")
    else:
        for r in current_batch:
            st = "In Progress" if r.status == "IN_PROGRESS" else "Waiting"
            lines.append(
                f"🟢 <b>MATCH #{abs(r.chat_id) % 10000}</b>\n"
                f"• Players : {len(r.players)}\n"
                f"• Status  : {st}\n"
                f"• Host    : {r.host_name}\n"
                f"• Started : Active\n"
            )

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"Total Active Matches: {total}")

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm_match_p:{page-1}:{admin_id}"))
    nav.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm_match_p:{page+1}:{admin_id}"))

    markup = InlineKeyboardMarkup(inline_keyboard=[nav, [InlineKeyboardButton(text="❌ Close", callback_data=f"adm_cancel:{admin_id}")]])

    if isinstance(message_or_cb, Message):
        await message_or_cb.reply("\n".join(lines), reply_markup=markup)
    else:
        await message_or_cb.message.edit_text("\n".join(lines), reply_markup=markup)

@admin_router.callback_query(F.data.startswith("adm_match_p:"))
async def cb_match_page(callback: CallbackQuery):
    parts = callback.data.split(":")
    page = int(parts[1])
    admin_id = int(parts[2])

    if callback.from_user.id != admin_id or not database.is_admin(callback.from_user.id):
        await callback.answer("🔒 Unauthorized.", show_alert=True)
        return

    await render_active_matches_page(callback, page, admin_id)
    await callback.answer()

@admin_router.message(Command("stopmatch"))
async def cmd_stopmatch(message: Message):
    if not database.is_admin(message.from_user.id):
        return

    arg = message.text.replace("/stopmatch", "").strip()
    if not arg:
        await message.reply("⚠️ Usage: <code>/stopmatch &lt;match_id&gt;</code>")
        return

    target_room = None
    for chat_id, r in GAMES.items():
        if str(abs(chat_id) % 10000) == arg or str(chat_id) == arg:
            target_room = r
            break

    if not target_room:
        await message.reply("❌ Match not found or already closed.")
        return

    match_id = abs(target_room.chat_id) % 10000
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🛑 STOP MATCH", callback_data=f"adm_stop_yes:{target_room.chat_id}:{message.from_user.id}"),
            InlineKeyboardButton(text="❌ CANCEL", callback_data=f"adm_cancel:{message.from_user.id}")
        ]
    ])

    await message.reply(
        "⚠️ <b>STOP MATCH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎮 Match  : #{match_id}\n"
        "🎴 Game   : Call 31\n"
        f"👥 Players: {len(target_room.players)}\n"
        f"📊 Status : {target_room.status}\n\n"
        "Are you sure?",
        reply_markup=markup
    )

@admin_router.callback_query(F.data.startswith("adm_stop_yes:"))
async def cb_stop_match_confirm(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split(":")
    chat_id = int(parts[1])
    admin_id = int(parts[2])

    if callback.from_user.id != admin_id or not database.is_admin(callback.from_user.id):
        await callback.answer("🔒 Unauthorized.", show_alert=True)
        return

    room = GAMES.get(chat_id)
    if room:
        if room.active_timer_task and not room.active_timer_task.done():
            room.active_timer_task.cancel()
        del GAMES[chat_id]

        try:
            await bot.send_message(
                chat_id,
                f"🛑 <b>MATCH TERMINATED:</b> Match was stopped by Administrator (@{callback.from_user.username or 'Admin'})."
            )
        except Exception:
            pass

        database.log_admin_action(callback.from_user.id, callback.from_user.full_name, "STOP_MATCH", str(chat_id), room.status, "TERMINATED")

    match_id = abs(chat_id) % 10000
    await callback.message.edit_text(
        "🛑 <b>MATCH STOPPED</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎮 Match : #{match_id}\n"
        f"👤 Stopped by: @{callback.from_user.username or callback.from_user.full_name}\n\n"
        "All players have been safely removed from the active match."
    )
    await callback.answer()

@admin_router.message(Command("announce"))
async def cmd_announce(message: Message, state: FSMContext):
    if not database.is_admin(message.from_user.id):
        return

    await state.set_state(StatEditStates.waiting_for_announcement)
    await state.update_data(admin_id=message.from_user.id)
    await message.reply(
        "📢 <b>ANNOUNCEMENT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Send your announcement content:\n\n"
        "<i>Use /cancel to abort.</i>"
    )

@admin_router.message(StatEditStates.waiting_for_announcement)
async def process_announcement_text(message: Message, state: FSMContext):
    data = await state.get_data()
    if message.from_user.id != data.get("admin_id"):
        return

    if message.text and message.text.startswith("/cancel"):
        await state.clear()
        await message.reply("❌ Announcement cancelled.")
        return

    await state.update_data(announcement_text=message.text)
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📤 SEND", callback_data=f"adm_ann_send:{message.from_user.id}"),
            InlineKeyboardButton(text="❌ CANCEL", callback_data=f"adm_cancel:{message.from_user.id}")
        ]
    ])
    await message.reply(
        "📢 <b>ANNOUNCEMENT PREVIEW</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{message.text}\n\n"
        "━━━━━━━━━━━━━━━━━━━━",
        reply_markup=markup
    )

@admin_router.callback_query(F.data.startswith("adm_ann_send:"))
async def cb_send_announcement(callback: CallbackQuery, state: FSMContext, bot: Bot):
    admin_id = int(callback.data.split(":")[1])
    if callback.from_user.id != admin_id or not database.is_admin(callback.from_user.id):
        await callback.answer("🔒 Unauthorized.", show_alert=True)
        return

    data = await state.get_data()
    content = data.get("announcement_text")
    await state.clear()

    await callback.message.edit_text("⏳ <i>Broadcasting announcement...</i>")

    users = database.get_all_registered_users()
    groups = database.get_registered_groups()

    u_sent, u_fail = 0, 0
    g_sent, g_fail = 0, 0

    for uid in users:
        try:
            await bot.send_message(uid, content)
            u_sent += 1
            await asyncio.sleep(0.04)
        except Exception:
            u_fail += 1

    for grp in groups:
        if grp.get("is_active"):
            try:
                await bot.send_message(grp["chat_id"], content)
                g_sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                g_fail += 1

    database.log_admin_action(callback.from_user.id, callback.from_user.full_name, "ANNOUNCEMENT", "ALL", "PENDING", f"U:{u_sent}/G:{g_sent}")

    total_deliveries = u_sent + g_sent
    total_targets = len(users) + len(groups)

    await callback.message.edit_text(
        "📢 <b>ANNOUNCEMENT SENT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "👤 <b>USERS</b>\n"
        f"• Total   : {len(users):,}\n"
        f"• ✅ Sent : {u_sent:,}\n"
        f"• ❌ Failed: {u_fail:,}\n\n"
        "🏟️ <b>GROUPS</b>\n"
        f"• Total   : {len(groups):,}\n"
        f"• ✅ Sent : {g_sent:,}\n"
        f"• ❌ Failed: {g_fail:,}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>TOTAL DELIVERY</b>\n"
        f"{total_deliveries:,} / {total_targets:,}\n\n"
        "🟢 Completed"
    )
    await callback.answer()

@admin_router.message(Command("groups"))
async def cmd_groups(message: Message):
    if not database.is_admin(message.from_user.id):
        return
    await render_groups_page(message, 1, message.from_user.id)

async def render_groups_page(message_or_cb, page: int, admin_id: int):
    all_groups = database.get_registered_groups()
    total_groups = len(all_groups)
    active_count = sum(1 for g in all_groups if g.get("is_active"))
    inactive_count = total_groups - active_count
    active_matches = len([g for g in GAMES.values() if g.status in ("LOBBY", "IN_PROGRESS")])

    per_page = 4
    total_pages = max(1, math.ceil(total_groups / per_page))
    page = min(max(1, page), total_pages)

    start_idx = (page - 1) * per_page
    batch = all_groups[start_idx:start_idx + per_page]

    lines = [
        "🏟️ <b>REGISTERED ARENAS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📊 <b>OVERVIEW</b>\n"
        f"• Total Groups   : {total_groups}\n"
        f"• Active         : {active_count}\n"
        f"• Inactive       : {inactive_count}\n"
        f"• Active Matches : {active_matches}\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🏟️ <b>GROUP LIST</b>\n"
    ]
    if not batch:
        lines.append("<i>No groups registered yet.</i>")
    else:
        for idx, grp in enumerate(batch, start=start_idx + 1):
            st = "🟢 Active" if grp.get("is_active") else "🔴 Inactive"
            has_match = 1 if grp["chat_id"] in GAMES and GAMES[grp["chat_id"]].status in ("LOBBY", "IN_PROGRESS") else 0
            lines.append(
                f"{idx}. 🎮 {grp.get('title', 'Group')}\n"
                f"   ID: {grp['chat_id']}\n"
                f"   Status: {st}\n"
                f"   Active Match: {has_match}\n"
            )

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm_grp_p:{page-1}:{admin_id}"))
    nav.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm_grp_p:{page+1}:{admin_id}"))

    markup = InlineKeyboardMarkup(inline_keyboard=[nav, [InlineKeyboardButton(text="❌ Close", callback_data=f"adm_cancel:{admin_id}")]])

    if isinstance(message_or_cb, Message):
        await message_or_cb.reply("\n".join(lines), reply_markup=markup)
    else:
        await message_or_cb.message.edit_text("\n".join(lines), reply_markup=markup)

@admin_router.callback_query(F.data.startswith("adm_grp_p:"))
async def cb_group_page(callback: CallbackQuery):
    parts = callback.data.split(":")
    page = int(parts[1])
    admin_id = int(parts[2])

    if callback.from_user.id != admin_id or not database.is_admin(callback.from_user.id):
        await callback.answer("🔒 Unauthorized.", show_alert=True)
        return

    await render_groups_page(callback, page, admin_id)
    await callback.answer()

@admin_router.message(Command("botstats"))
async def cmd_botstats(message: Message):
    if not database.is_admin(message.from_user.id):
        return

    metrics = database.get_overall_bot_metrics()
    c31 = metrics["call31"]
    grp = metrics["groups"]
    active_m = len([g for g in GAMES.values() if g.status in ("LOBBY", "IN_PROGRESS")])

    text = (
        "📊 <b>DECK PLAY STATISTICS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "👤 <b>USERS</b>\n"
        f"• Registered : {c31.get('registered_users', 0):,}\n"
        f"• Active     : {c31.get('active_users', 0):,}\n\n"
        "🏟️ <b>GROUPS</b>\n"
        f"• Registered : {grp.get('registered_groups', 0):,}\n"
        f"• Active     : {grp.get('active_groups', 0):,}\n\n"
        "🎴 <b>CALL 31</b>\n"
        f"• Total Games     : {c31.get('total_games_played', 0):,}\n"
        f"• Completed Games : {c31.get('total_games_played', 0):,}\n"
        f"• Active Matches  : {active_m}\n\n"
        "🏆 <b>RESULTS</b>\n"
        f"• Wins        : {c31.get('total_wins', 0):,}\n"
        f"• Joint Wins  : {c31.get('total_joint_wins', 0):,}\n"
        f"• Survived    : {c31.get('total_survived', 0):,}\n"
        f"• Exact 31    : {c31.get('total_exact_31', 0):,}\n"
        f"• 30.5        : {c31.get('total_exact_30_5', 0):,}\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )
    await message.reply(text)

@admin_router.callback_query(F.data.startswith("adm_cancel:"))
async def cb_admin_cancel(callback: CallbackQuery, state: FSMContext):
    admin_id = int(callback.data.split(":")[1])
    if callback.from_user.id != admin_id:
        await callback.answer("🔒 Unauthorized.", show_alert=True)
        return

    await state.clear()
    await callback.message.edit_text("❌ <b>Action Cancelled.</b>")
    await callback.answer()

@admin_router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer()

@admin_router.message(Command("adminhelp", "admin"))
async def cmd_adminhelp(message: Message):
    user_id = message.from_user.id
    
    # Normal user protection
    if not database.is_admin(user_id):
        return

    is_owner_user = database.is_owner(user_id)

    lines = [
        "🛡️ <b>DECK PLAY — ADMIN COMMAND GUIDE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
    ]

    if is_owner_user:
        lines.extend([
            "👑 <b>OWNER PRIVILEGES</b>\n"
            "• <code>/setstats &lt;user&gt;</code> — Interactive Call 31 stats editor\n"
            "• <code>/resetstats &lt;user&gt;</code> — Reset player's Call 31 records\n"
            "• <code>/addadmin &lt;user&gt;</code> — Grant operational admin access\n"
            "• <code>/removeadmin &lt;user&gt;</code> — Revoke admin privileges\n"
            "• <code>/admins</code> — List authorized administrators\n"
            "• <code>/maintenance</code> — Toggle game maintenance ON/OFF\n\n"
        ])

    lines.extend([
        "⚔️ <b>OPERATIONAL COMMANDS</b>\n"
        "• <code>/playerinfo &lt;user&gt;</code> — Inspect detailed player stats & winrate\n"
        "• <code>/activematches</code> — Monitor live running matches\n"
        "• <code>/stopmatch &lt;id&gt;</code> — Force kill stuck/frozen match\n"
        "• <code>/announce</code> — Broadcast message to all DMs + Arenas\n"
        "• <code>/groups</code> — Inspect registered arenas & activity\n"
        "• <code>/botstats</code> — Overall bot performance metrics\n"
        "• <code>/adminhelp</code> — View this command manual\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Note: <code>&lt;user&gt;</code> can be a reply, numeric ID, or @username.</i>"
    ])

    await message.reply("".join(lines))
import asyncio
import logging
import os
import random
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand

import config
from cards_and_scoring import Card, calculate_hand_score, format_score
from game_state import GameRoom, Player, GAMES, get_game_lock, start_new_round
import menu
import turn_ui
import database

logging.basicConfig(level=logging.INFO)

database.init_db()

bot = Bot(
    token=config.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

def get_chat_link(chat_id: int) -> str:
    clean_id = str(chat_id).replace("-100", "")
    return f"https://t.me/c/{clean_id}/999999999"

def cancel_timer(game: GameRoom):
    if game.active_timer_task and not game.active_timer_task.done():
        try:
            curr_task = asyncio.current_task()
            if game.active_timer_task != curr_task:
                game.active_timer_task.cancel()
        except Exception:
            pass
    game.active_timer_task = None

def schedule_turn_timer(game: GameRoom):
    cancel_timer(game)
    game.active_timer_task = asyncio.create_task(run_turn_timer(game.chat_id))

async def run_lobby_inactivity_timer(chat_id: int):
    try:
        await asyncio.sleep(180)  # 3 minutes
        async with get_game_lock(chat_id):
            game = GAMES.get(chat_id)
            if not game or game.status != "LOBBY":
                return

            host_tag = f"<a href='tg://user?id={game.host_id}'>{game.host_name}</a>"
            del GAMES[chat_id]
            await bot.send_message(
                chat_id,
                f"⌛ <b>Lobby Expired!</b>\n"
                f"{host_tag} dwara banayi gayi lobby 3 minute me start na hone ki wajah se cancel kar di gayi hai.\n"
                f"Naya game shuru karne ke liye /start ya /deck run karein."
            )
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logging.error(f"Lobby timer error in chat {chat_id}: {e}", exc_info=True)

async def check_and_announce_host(game: GameRoom):
    old_host_id = game.host_id
    new_h = game.reassign_host_if_needed()
    if new_h and new_h.user_id != old_host_id:
        tag = f"<a href='tg://user?id={new_h.user_id}'>{new_h.name}</a>"
        await bot.send_message(game.chat_id, f"👑 <b>Host Reassigned!</b> {tag} is now the room Host.")

async def run_turn_timer(chat_id: int):
    try:
        await asyncio.sleep(config.TURN_TIME_SECONDS)
        async with get_game_lock(chat_id):
            game = GAMES.get(chat_id)
            if not game or game.status != "IN_PROGRESS":
                return

            player = game.current_player
            if not player:
                return

            tag = f"<a href='tg://user?id={player.user_id}'>{player.name}</a>"

            if player.warning_count == 0:
                player.warning_count = 1
                try:
                    await bot.send_message(
                        player.user_id,
                        f"⚠️ <b>WARNING (1/2)</b>\nAapne {config.TURN_TIME_SECONDS}s ke andar move nahi kiya!\n"
                        "Aapki turn skip kar di gayi hai. Agar agle turn par bhi move nahi kiya toh aap match se remove ho jayenge."
                    )
                except Exception:
                    pass

                await bot.send_message(chat_id, f"⏱️ {tag} missed turn! <b>(Warning 1/2)</b> — Skipped to next player.")
                database.update_stat(player.user_id, player.name, "passes")
                await advance_turn(game, passed=True, last_action=f"{player.name} timed out")

            else:
                player.is_active = False
                player.lives = 0
                
                if player.cards:
                    game.unused_deck.extend(player.cards)
                    random.shuffle(game.unused_deck)
                    player.cards.clear()

                try:
                    await bot.send_message(
                        player.user_id,
                        "🚫 Lagatar 2 turns miss karne ki wajah se aapko match se remove kar diya gaya hai."
                    )
                except Exception:
                    pass

                await bot.send_message(
                    chat_id, 
                    f"🚫 {tag} has been <b>REMOVED</b> (2 missed turns in a row).\nUnke cards wapas deck me mix kar diye gaye hain."
                )
                await check_and_announce_host(game)

                if len(game.active_players) <= 1:
                    await end_game(game)
                    return

                await advance_turn(game, passed=False, last_action=f"{player.name} removed for inactivity")

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logging.error(f"Timer error in chat {chat_id}: {e}", exc_info=True)

async def send_player_turn(game: GameRoom, player: Player):
    schedule_turn_timer(game)
    text = turn_ui.render_dm_hand_view(player.cards, game.table_cards)

    call_locked = (game.caller_id is not None)
    markup = turn_ui.get_dm_turn_buttons(game.chat_id, is_call_locked=call_locked)

    try:
        await bot.send_message(player.user_id, text, reply_markup=markup)
    except Exception as e:
        logging.warning(f"Could not send DM to player {player.user_id}: {e}")
        tag = f"<a href='tg://user?id={player.user_id}'>{player.name}</a>"
        dm_alert_markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👉 Click Here to Receive Cards", url=f"https://t.me/{config.BOT_USERNAME}?start=game")]
        ])
        await bot.send_message(
            game.chat_id,
            f"⚠️ {tag}, aapka DM closed hai! Neeche button par click karke /start dabayein taaki cards dikhein:",
            reply_markup=dm_alert_markup
        )

async def advance_turn(game: GameRoom, passed: bool = False, last_action: str = None):
    cancel_timer(game)

    if passed:
        game.consecutive_passes += 1
        if game.consecutive_passes >= config.PASS_REFRESH_THRESHOLD:
            if len(game.unused_deck) >= 3:
                game.table_cards = [game.unused_deck.pop(), game.unused_deck.pop(), game.unused_deck.pop()]
                game.consecutive_passes = 0
                last_action = "🔄 3 Consecutive Passes hue! Table ke cards badal diye gaye hain."
                await bot.send_message(
                    game.chat_id, 
                    "🔄 <b>3 Consecutive Passes!</b> Table ke cards naye deck se badal diye gaye hain!"
                )
            else:
                game.consecutive_passes = 0
    else:
        game.consecutive_passes = 0

    if game.caller_id is not None:
        curr = game.current_player
        if curr and curr.user_id != game.caller_id:
            curr.has_final_turn_taken = True

        remaining = [p for p in game.active_players if p.user_id != game.caller_id and not p.has_final_turn_taken]
        if not remaining:
            await resolve_round(game)
            return

    if len(game.active_players) <= 1:
        await end_game(game)
        return

    while True:
        game.current_turn_index = (game.current_turn_index + 1) % len(game.turn_order)
        nxt = game.current_player
        if nxt and nxt.is_active and nxt.lives > 0:
            if game.caller_id is not None and (nxt.user_id == game.caller_id or nxt.has_final_turn_taken):
                continue
            break

    await bot.send_message(
        game.chat_id,
        turn_ui.render_group_turn_view(game, last_action),
        reply_markup=turn_ui.get_group_turn_markup(config.BOT_USERNAME)
    )

    if game.current_player:
        await send_player_turn(game, game.current_player)

async def handle_31_call(game: GameRoom, player: Player):
    cancel_timer(game)
    database.update_stat(player.user_id, player.name, "exact_31")
    database.update_stat(player.user_id, player.name, "round_wins")
    database.update_stat(player.user_id, player.name, "rounds_survived")

    tag = f"<a href='tg://user?id={player.user_id}'>{player.name}</a>"

    lines = [
        "⚡ <b>PERFECT SCORE 31!</b>\n",
        f"🎉 {tag} completed <b>31 Points</b>! Automatic Call.\n",
        "🎴 <b>ALL PLAYERS CARDS REVEAL:</b>"
    ]

    scores = []
    for p in game.active_players:
        sc = calculate_hand_score(p.cards)
        scores.append((p, sc))

    scores.sort(key=lambda x: x[1], reverse=True)

    for p, sc in scores:
        c_str = " ".join(f"[{c.suit.value} {c.rank}]" for c in p.cards)
        crown = " 👑 (31 PTS)" if p.user_id == player.user_id else ""
        lines.append(f"• <b>{p.name}</b>: <code>{c_str}</code> ➔ <b>{format_score(sc)} pts</b>{crown}")

    lines.append("\n💔 <i>All other active players lose 1 life!</i>")

    for p in game.active_players:
        if p.user_id != player.user_id:
            p.lives -= 1
            database.update_stat(p.user_id, p.name, "lives_lost")

    if not game.first_life_lost:
        game.first_life_lost = True
        game.joining_open = False
        lines.append("🔒 <b>Joining is now permanently closed</b> (first life lost).")

    await bot.send_message(game.chat_id, "\n".join(lines))
    await finalize_round_eliminations(game)

async def resolve_round(game: GameRoom):
    cancel_timer(game)
    lines = ["🏁 <b>ROUND OVER — REVEAL:</b>\n"]
    scores = []

    for p in game.active_players:
        sc = calculate_hand_score(p.cards)
        scores.append((p, sc))
        if sc == 30.5:
            database.update_stat(p.user_id, p.name, "exact_30_5")

    scores.sort(key=lambda x: x[1], reverse=True)

    for p, sc in scores:
        c_str = " ".join(f"[{c.suit.value} {c.rank}]" for c in p.cards)
        lines.append(f"• <b>{p.name}</b>: <code>{c_str}</code> ➔ <b>{format_score(sc)} pts</b>")

    max_sc = scores[0][1]
    round_winners = [p for p, sc in scores if sc == max_sc]
    for rw in round_winners:
        database.update_stat(rw.user_id, rw.name, "round_wins")

    min_sc = scores[-1][1]
    losers = [p for p, sc in scores if sc == min_sc]

    for p in game.active_players:
        if p in losers:
            database.update_stat(p.user_id, p.name, "lives_lost")
        else:
            database.update_stat(p.user_id, p.name, "rounds_survived")

    lines.append(f"\nLowest score: <b>{format_score(min_sc)}</b>")
    l_names = []
    for p in losers:
        p.lives -= 1
        l_names.append(f"<a href='tg://user?id={p.user_id}'>{p.name}</a>")

    lines.append(f"💔 Lost 1 life: {', '.join(l_names)}")

    if not game.first_life_lost and losers:
        game.first_life_lost = True
        game.joining_open = False
        lines.append("🔒 <b>Joining is now permanently closed</b> (first life lost).")

    await bot.send_message(game.chat_id, "\n".join(lines))
    await finalize_round_eliminations(game)

async def finalize_round_eliminations(game: GameRoom):
    for p in list(game.players.values()):
        if p.lives <= 0 and p.is_active:
            p.is_active = False
            if p.cards:
                game.unused_deck.extend(p.cards)
                random.shuffle(game.unused_deck)
                p.cards.clear()
            tag = f"<a href='tg://user?id={p.user_id}'>{p.name}</a>"
            await bot.send_message(game.chat_id, f"💀 {tag} has been eliminated!")

    await check_and_announce_host(game)

    if len(game.active_players) <= 1:
        await end_game(game)
        return

    game.round_number += 1
    await bot.send_message(game.chat_id, f"🚀 <b>Starting Round {game.round_number}...</b>")
    start_new_round(game)
    await bot.send_message(
        game.chat_id,
        turn_ui.render_group_turn_view(game),
        reply_markup=turn_ui.get_group_turn_markup(config.BOT_USERNAME)
    )
    if game.current_player:
        await send_player_turn(game, game.current_player)

async def end_game(game: GameRoom):
    cancel_timer(game)
    game.status = "ENDED"
    participants = [(p.user_id, p.name) for p in game.players.values()]

    if len(game.active_players) == 1:
        winner = game.active_players[0]
        tag = f"<a href='tg://user?id={winner.user_id}'>{winner.name}</a>"
        database.record_game_finish(winner.user_id, winner.name, participants)
        await bot.send_message(
            game.chat_id,
            f"🏆 <b>GAME OVER</b>\n\nWinner: {tag} with {winner.lives} ❤️ remaining!"
        )
    else:
        database.record_game_finish(0, "None", participants)
        await bot.send_message(game.chat_id, "🏆 <b>GAME OVER</b> — No survivors remaining!")

    if game.chat_id in GAMES:
        del GAMES[game.chat_id]

# --- COMMAND HANDLERS ---

@dp.message(Command("start"))
async def handle_start(message: Message):
    if message.chat.type == "private":
        await message.reply(
            "✅ <b>Bot Activated!</b>\n\n"
            "Aapka private chat connect ho gaya hai. Group me match chalne par aapke secret cards aur move buttons yahan deliver honge."
        )
        return

    await message.reply(
        "🎮 <b>CHOOSE A GAME TO START:</b>", 
        reply_markup=turn_ui.get_play_games_markup(message.chat.id)
    )

@dp.message(Command("deck"))
async def cmd_deck(message: Message):
    if message.chat.type == "private":
        await message.reply("🎮 <b>Deck Games Hub:</b> Group me /start ya /deck run karein!")
        return

    text = menu.render_hub_welcome(message.chat.title or "Group")
    markup = menu.get_game_categories_markup(message.chat.id)
    await message.answer(text, reply_markup=markup)

@dp.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "🎴 <b>DECK GAMES — HELP & COMMANDS</b>\n"
        "─────────────────────────\n"
        "/start — Start / Launch a game\n"
        "/deck — Open Games Menu Hub\n"
        "/join — Join current game / lobby\n"
        "/leave — Leave current game or lobby\n"
        "/remove — Start a vote to remove a player (by reply)\n"
        "/endgame — Host ends game / Players start end-game vote\n"
        "/profile — View your game stats\n"
        "/leaderboard — View top rankings\n"
        "/rules — View game rules & scoring guide\n"
        "/help — Show this help message"
    )
    await message.reply(help_text)

@dp.message(Command("rules"))
async def cmd_rules(message: Message):
    markup = turn_ui.get_hub_selection_markup("rules")
    await message.reply("📖 <b>RULES GUIDE</b>\nSelect a game to view complete rules:", reply_markup=markup)

@dp.message(Command("profile", "me"))
async def cmd_profile(message: Message):
    markup = turn_ui.get_hub_selection_markup("profile")
    await message.reply("📊 <b>STATS HUB</b>\nSelect a game to view your profile stats:", reply_markup=markup)

@dp.message(Command("leaderboard", "top"))
async def cmd_leaderboard(message: Message):
    markup = turn_ui.get_hub_selection_markup("leaderboard")
    await message.reply("🏆 <b>LEADERBOARDS</b>\nSelect a game to view rankings:", reply_markup=markup)

@dp.message(Command("join"))
async def cmd_join(message: Message):
    if message.chat.type == "private":
        await message.reply("❌ Game kisi group me join karein.")
        return

    chat_id = message.chat.id
    async with get_game_lock(chat_id):
        game = GAMES.get(chat_id)
        if not game:
            await message.reply("❌ Koi active game ya lobby nahi hai. /start se game shuru karein.")
            return

        user_id = message.from_user.id
        if user_id in game.players and game.players[user_id].is_active and game.players[user_id].lives > 0:
            await message.reply("Aap pehle se game me hain!")
            return

        if len(game.players) >= config.MAX_PLAYERS:
            await message.reply(f"Game full ho chuka hai ({config.MAX_PLAYERS} max).")
            return

        dm_btn = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📩 Activate Bot DM", url=f"https://t.me/{config.BOT_USERNAME}?start=join")]
        ])

        if game.status == "LOBBY":
            game.players[user_id] = Player(
                user_id=user_id,
                name=message.from_user.full_name,
                username=message.from_user.username
            )
            await message.reply(
                f"✅ <b>{message.from_user.full_name}</b> lobby me shamil ho gaye!\n"
                "<i>Agar pehli baar khel rahe hain toh neeche button click karke DM verify kar lein.</i>",
                reply_markup=dm_btn
            )
            return

        if game.status == "IN_PROGRESS":
            if not game.joining_open or game.first_life_lost:
                await message.reply("🔒 <b>Joining is closed!</b> Pehli life lose hone ke baad join nahi kar sakte.")
                return

            if len(game.unused_deck) < 3:
                await message.reply("❌ Deck me naye player ke liye cards nahi bache hain.")
                return

            new_p = Player(
                user_id=user_id,
                name=message.from_user.full_name,
                username=message.from_user.username,
                cards=[game.unused_deck.pop(), game.unused_deck.pop(), game.unused_deck.pop()]
            )
            game.players[user_id] = new_p
            game.turn_order.append(user_id)

            tag = f"<a href='tg://user?id={user_id}'>{message.from_user.full_name}</a>"
            await message.reply(
                f"🎉 {tag} mid-game join ho gaye!\n"
                "Cards receive karne ke liye ensure karein ki aapne bot ko DM kiya ho:",
                reply_markup=dm_btn
            )

@dp.message(Command("leave"))
async def cmd_leave(message: Message):
    if message.chat.type == "private":
        return

    chat_id = message.chat.id
    async with get_game_lock(chat_id):
        game = GAMES.get(chat_id)
        if not game:
            await message.reply("❌ Koi active game nahi chal raha hai.")
            return

        user_id = message.from_user.id
        if user_id not in game.players or not game.players[user_id].is_active:
            await message.reply("Aap is game ka hissa nahi hain.")
            return

        player = game.players[user_id]

        if game.status == "LOBBY":
            del game.players[user_id]
            await message.reply(f"🚪 <b>{player.name}</b> ne lobby chhod di.")
            if user_id == game.host_id:
                if game.players:
                    next_h = next(iter(game.players.values()))
                    game.host_id = next_h.user_id
                    game.host_name = next_h.name
                    await message.answer(f"👑 Naye host bane: <b>{next_h.name}</b>")
                else:
                    cancel_timer(game)
                    del GAMES[chat_id]
                    await message.answer("🚪 Sabhi ke nikalne par lobby band ho gayi.")
            return

        player.is_active = False
        player.lives = 0
        if player.cards:
            game.unused_deck.extend(player.cards)
            random.shuffle(game.unused_deck)
            player.cards.clear()

        tag = f"<a href='tg://user?id={player.user_id}'>{player.name}</a>"
        await message.reply(f"🚪 {tag} ne game chhod diya aur eliminate ho gaye.")

        await check_and_announce_host(game)

        if len(game.active_players) <= 1:
            await end_game(game)
            return

        if game.current_player and game.current_player.user_id == user_id:
            await advance_turn(game, passed=False, last_action=f"{player.name} left the game")

@dp.message(Command("remove"))
async def cmd_remove(message: Message):
    if message.chat.type == "private":
        return

    chat_id = message.chat.id
    async with get_game_lock(chat_id):
        game = GAMES.get(chat_id)
        if not game or game.status != "IN_PROGRESS":
            await message.reply("❌ Remove vote sirf ongoing game ke dauran chal sakta hai.")
            return

        user_id = message.from_user.id
        if user_id not in game.players or not game.players[user_id].is_active:
            await message.reply("❌ Sirf active players hi removal vote shuru kar sakte hain.")
            return

        if not message.reply_to_message or not message.reply_to_message.from_user:
            await message.reply("⚠️ Jis player ko remove karna hai, uske message par reply karke /remove likhein.")
            return

        target_id = message.reply_to_message.from_user.id
        target = game.players.get(target_id)

        if not target or not target.is_active or target.lives <= 0:
            await message.reply("❌ Target player active nahi hai.")
            return

        if target_id == user_id:
            await message.reply("❌ Aap khud ke khilaf remove vote nahi start kar sakte.")
            return

        game.active_remove_votes[target_id] = {user_id}
        target_tag = f"<a href='tg://user?id={target.user_id}'>{target.name}</a>"
        caller_tag = f"<a href='tg://user?id={user_id}'>{message.from_user.full_name}</a>"

        await message.answer(
            f"🗳️ <b>REMOVE VOTE STARTED!</b>\n\n"
            f"{caller_tag} wants to remove {target_tag}.\n"
            f"Votes: <b>1/2</b>\n"
            f"Need 1 more active player vote to remove!",
            reply_markup=turn_ui.get_remove_vote_markup(chat_id, target_id)
        )

@dp.message(Command("endgame"))
async def cmd_endgame(message: Message):
    if message.chat.type == "private":
        return

    chat_id = message.chat.id
    async with get_game_lock(chat_id):
        game = GAMES.get(chat_id)
        if not game:
            await message.reply("❌ Koi active game nahi chal raha hai.")
            return

        user_id = message.from_user.id

        # FIX: Agar game sirf LOBBY stage me hai aur start nahi hua, toh koi bhi close kar sake
        if game.status == "LOBBY":
            cancel_timer(game)
            del GAMES[chat_id]
            h_tag = f"<a href='tg://user?id={game.host_id}'>{game.host_name}</a>"
            await message.answer(f"🚪 <b>Lobby Closed!</b> {h_tag} dwara banayi gayi lobby close kar di gayi hai.")
            return

        # Ongoing match me active player restriction
        if user_id not in game.players or not game.players[user_id].is_active:
            await message.reply("❌ Sirf game ke active players hi ongoing match ko end kar sakte hain.")
            return

        if user_id == game.host_id:
            cancel_timer(game)
            del GAMES[chat_id]
            await message.answer("🛑 <b>Game Host dwara forcefully terminate kar diya gaya hai.</b>")
            return

        active_count = len(game.active_players)
        if active_count <= 2:
            await message.reply("❌ 2 players game me non-host game force-end nahi kar sakta (2 votes impossible).")
            return

        game.endgame_votes = {user_id}
        voter_tag = f"<a href='tg://user?id={user_id}'>{message.from_user.full_name}</a>"

        await message.answer(
            f"🛑 <b>END GAME VOTE STARTED!</b>\n\n"
            f"{voter_tag} has voted to end the game.\n"
            f"Votes: <b>1/2</b>\n"
            f"Need 1 more active player vote to end the match!",
            reply_markup=turn_ui.get_endgame_vote_markup(chat_id)
        )

# --- CALLBACK ROUTERS ---

@dp.callback_query(F.data.startswith("vote_rem:"))
async def handle_remove_vote(callback: CallbackQuery):
    parts = callback.data.split(":")
    chat_id = int(parts[1])
    target_id = int(parts[2])
    voter_id = callback.from_user.id

    async with get_game_lock(chat_id):
        game = GAMES.get(chat_id)
        if not game or game.status != "IN_PROGRESS":
            await callback.answer("Game active nahi hai.", show_alert=True)
            return

        if target_id not in game.active_remove_votes:
            await callback.answer("Ye vote poll ab active nahi hai.", show_alert=True)
            return

        if voter_id == target_id:
            await callback.answer("❌ Aap khud ke removal par vote nahi de sakte!", show_alert=True)
            return

        voter = game.players.get(voter_id)
        if not voter or not voter.is_active or voter.lives <= 0:
            await callback.answer("❌ Sirf active players vote kar sakte hain!", show_alert=True)
            return

        votes_set = game.active_remove_votes[target_id]
        if voter_id in votes_set:
            await callback.answer("Aap pehle hi vote kar chuke hain!", show_alert=True)
            return

        votes_set.add(voter_id)
        await callback.answer("Vote registered!")

        if len(votes_set) >= 2:
            del game.active_remove_votes[target_id]
            target = game.players.get(target_id)
            if target and target.is_active:
                target.is_active = False
                target.lives = 0
                if target.cards:
                    game.unused_deck.extend(target.cards)
                    random.shuffle(game.unused_deck)
                    target.cards.clear()

                tag = f"<a href='tg://user?id={target.user_id}'>{target.name}</a>"
                await callback.message.edit_text(f"🚫 <b>VOTE PASSED!</b> {tag} has been removed from the game.")

                await check_and_announce_host(game)

                if len(game.active_players) <= 1:
                    await end_game(game)
                    return

                if game.current_player and game.current_player.user_id == target_id:
                    await advance_turn(game, passed=False, last_action=f"{target.name} was vote-removed")

@dp.callback_query(F.data.startswith("vote_end:"))
async def handle_endgame_vote(callback: CallbackQuery):
    parts = callback.data.split(":")
    chat_id = int(parts[1])
    voter_id = callback.from_user.id

    async with get_game_lock(chat_id):
        game = GAMES.get(chat_id)
        if not game or game.status != "IN_PROGRESS":
            await callback.answer("Game active nahi hai.", show_alert=True)
            return

        voter = game.players.get(voter_id)
        if not voter or not voter.is_active or voter.lives <= 0:
            await callback.answer("❌ Sirf active players vote kar sakte hain!", show_alert=True)
            return

        if voter_id in game.endgame_votes:
            await callback.answer("Aap pehle hi vote kar chuke hain!", show_alert=True)
            return

        game.endgame_votes.add(voter_id)
        await callback.answer("Vote registered!")

        if len(game.endgame_votes) >= 2:
            cancel_timer(game)
            del GAMES[chat_id]
            await callback.message.edit_text("🛑 <b>VOTE PASSED:</b> The game has been ended by player majority.")

@dp.callback_query(F.data.startswith("hub_sel:"))
async def handle_hub_selection(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    cat = parts[1]
    game_type = parts[2]

    if game_type == "call31":
        if cat == "profile":
            stats = database.get_user_stats(callback.from_user.id)
            text = turn_ui.render_call31_profile(stats, callback.from_user.full_name)
        elif cat == "leaderboard":
            top_players = database.get_leaderboard(10)
            user_rank = database.get_user_rank(callback.from_user.id)
            text = turn_ui.render_call31_leaderboard(top_players, user_rank)
        else:
            text = turn_ui.render_call31_rules()

        back_markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Back to Selection", callback_data=f"hub_back:{cat}")]
        ])
        await callback.message.edit_text(text, reply_markup=back_markup)

@dp.callback_query(F.data.startswith("hub_back:"))
async def handle_hub_back(callback: CallbackQuery):
    await callback.answer()
    cat = callback.data.split(":")[1]
    markup = turn_ui.get_hub_selection_markup(cat)
    title = "STATS HUB" if cat == "profile" else ("LEADERBOARDS" if cat == "leaderboard" else "RULES GUIDE")
    await callback.message.edit_text(f"📊 <b>{title}</b>\nSelect a game:", reply_markup=markup)

@dp.callback_query(F.data.startswith("hub:"))
async def handle_hub(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    action = parts[1]

    if action == "launch_31":
        chat_id = int(parts[2])
        async with get_game_lock(chat_id):
            if chat_id in GAMES and GAMES[chat_id].status != "ENDED":
                active_game = GAMES[chat_id]
                h_name = active_game.host_name or "Unknown"
                h_tag = f"<a href='tg://user?id={active_game.host_id}'>{h_name}</a>"

                if active_game.status == "LOBBY":
                    await callback.message.reply(
                        f"⚠️ <b>Lobby pehle se open hai!</b>\n"
                        f"👑 <b>Host:</b> {h_tag}\n\n"
                        f"Aap /join karke khel sakte hain, ya /endgame chala kar lobby band kar sakte hain.\n"
                        f"<i>(Yeh lobby 3 min me auto-expire ho jayegi agar start nahi hui)</i>"
                    )
                else:
                    await callback.message.reply(
                        f"⚠️ <b>Match pehle se chal raha hai!</b>\n"
                        f"👑 <b>Host:</b> {h_tag}\n\n"
                        f"Ongoing game ko end karne ke liye /endgame vote karein."
                    )
                return

            room = GameRoom(
                chat_id=chat_id,
                host_id=callback.from_user.id,
                host_name=callback.from_user.full_name
            )
            host = Player(
                user_id=callback.from_user.id,
                name=callback.from_user.full_name,
                username=callback.from_user.username
            )
            room.players[host.user_id] = host
            GAMES[chat_id] = room

            # 3-minute lobby auto-expiry timer schedule
            cancel_timer(room)
            room.active_timer_task = asyncio.create_task(run_lobby_inactivity_timer(chat_id))

            await callback.message.edit_text(
                turn_ui.render_lobby_view(room),
                reply_markup=turn_ui.get_lobby_markup(chat_id, config.BOT_USERNAME)
            )

    elif action == "coming_soon":
        await callback.answer("Ye game agle update me aayega!", show_alert=True)

    elif action == "rules":
        await callback.message.edit_text(
            turn_ui.render_call31_rules(),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Back", callback_data="hub_back:rules")]
            ])
        )

@dp.callback_query(F.data.startswith("lobby:"))
async def handle_lobby(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    action = parts[1]
    chat_id = int(parts[2])

    async with get_game_lock(chat_id):
        room = GAMES.get(chat_id)
        if not room or room.status != "LOBBY":
            return

        user_id = callback.from_user.id

        if action == "join":
            if user_id in room.players:
                return
            if len(room.players) >= config.MAX_PLAYERS:
                return

            room.players[user_id] = Player(
                user_id=user_id,
                name=callback.from_user.full_name,
                username=callback.from_user.username
            )
            await callback.message.edit_text(
                turn_ui.render_lobby_view(room),
                reply_markup=turn_ui.get_lobby_markup(chat_id, config.BOT_USERNAME)
            )

        elif action == "leave":
            if user_id not in room.players:
                return

            del room.players[user_id]
            if user_id == room.host_id:
                if room.players:
                    next_h = next(iter(room.players.values()))
                    room.host_id = next_h.user_id
                    room.host_name = next_h.name
                else:
                    cancel_timer(room)
                    del GAMES[chat_id]
                    await callback.message.edit_text("🚪 Lobby closed as all players left.")
                    return

            await callback.message.edit_text(
                turn_ui.render_lobby_view(room),
                reply_markup=turn_ui.get_lobby_markup(chat_id, config.BOT_USERNAME)
            )

        elif action == "start":
            if user_id != room.host_id:
                return
            if len(room.players) < config.MIN_PLAYERS:
                await bot.send_message(chat_id, f"❌ Kam se kam {config.MIN_PLAYERS} players hone chahiye start karne ke liye.")
                return

            # Lobby auto-expiry timer cancel karo
            cancel_timer(room)

            room.status = "IN_PROGRESS"
            start_new_round(room)

            await callback.message.edit_text("🚀 <b>Game Starting! Dealing cards...</b>")

            await bot.send_message(
                room.chat_id,
                turn_ui.render_group_turn_view(room),
                reply_markup=turn_ui.get_group_turn_markup(config.BOT_USERNAME)
            )
            if room.current_player:
                await send_player_turn(room, room.current_player)

@dp.callback_query(F.data.startswith("turn:"))
async def handle_turn(callback: CallbackQuery):
    parts = callback.data.split(":")
    action = parts[1]

    if action == "call_locked":
        chat_id = int(parts[2])
        game = GAMES.get(chat_id)
        caller_name = "Player"
        if game and game.caller_id:
            caller = game.players.get(game.caller_id)
            if caller:
                caller_name = caller.name
        await callback.answer(f"🔒 Call Lock hai! {caller_name} ne pehle hi CALL kar diya hai.", show_alert=True)
        return

    chat_id = int(parts[2])
    await callback.answer()

    async with get_game_lock(chat_id):
        game = GAMES.get(chat_id)
        if not game or game.status != "IN_PROGRESS":
            return

        current = game.current_player
        if not current or current.user_id != callback.from_user.id:
            return

        current.warning_count = 0
        gc_link = get_chat_link(chat_id)

        if action == "pass":
            database.update_stat(current.user_id, current.name, "passes")
            msg_text = turn_ui.render_move_locked_in(current.cards, "You passed your turn.")
            await callback.message.edit_text(msg_text, reply_markup=turn_ui.get_back_to_group_markup(gc_link))
            await advance_turn(game, passed=True, last_action=f"{current.name} skipped / passed")

        elif action == "ex1":
            header = turn_ui.render_dm_cards_header(current.cards, game.table_cards)
            await callback.message.edit_text(
                f"{header}👇 <b>Select 1 card from your hand to give:</b>",
                reply_markup=turn_ui.get_exchange_step1_markup(chat_id, current)
            )

        elif action == "swap_h":
            hand_card_id = parts[3]
            selected_c = Card.from_id(hand_card_id)
            header = turn_ui.render_dm_cards_header(current.cards, game.table_cards)
            await callback.message.edit_text(
                f"{header}Selected: <b>[{selected_c.suit.value} {selected_c.rank}]</b>\n\n"
                "👇 <b>Choose which table card to take:</b>",
                reply_markup=turn_ui.get_exchange_step2_markup(chat_id, game.table_cards, hand_card_id)
            )

        elif action == "swap_t":
            hand_card_id = parts[3]
            table_card_id = parts[4]

            h_card = next((c for c in current.cards if c.id == hand_card_id), None)
            t_card = next((c for c in game.table_cards if c.id == table_card_id), None)

            if not h_card or not t_card:
                return

            current.cards.remove(h_card)
            game.table_cards.remove(t_card)
            current.cards.append(t_card)
            game.table_cards.append(h_card)

            database.update_stat(current.user_id, current.name, "ex_1")

            action_desc = f"{current.name} exchanged [{h_card.suit.value} {h_card.rank}] for [{t_card.suit.value} {t_card.rank}] from the table."
            msg_text = turn_ui.render_move_locked_in(current.cards, f"Exchanged [{h_card}] for [{t_card}]")
            await callback.message.edit_text(msg_text, reply_markup=turn_ui.get_back_to_group_markup(gc_link))

            if calculate_hand_score(current.cards) == 31.0:
                await handle_31_call(game, current)
                return

            await advance_turn(game, passed=False, last_action=action_desc)

        elif action == "exall_confirm":
            header = turn_ui.render_dm_cards_header(current.cards, game.table_cards)
            await callback.message.edit_text(
                f"{header}⚠️ <b>Exchange all 3 cards with the table?</b>",
                reply_markup=turn_ui.get_action_confirmation_markup(chat_id, "exall")
            )

        elif action == "exall_yes":
            old_h = list(current.cards)
            current.cards = list(game.table_cards)
            game.table_cards = old_h

            database.update_stat(current.user_id, current.name, "ex_all")

            action_desc = f"{current.name} exchanged all three cards with the table."
            msg_text = turn_ui.render_move_locked_in(current.cards, "Exchanged all 3 cards with the table.")
            await callback.message.edit_text(msg_text, reply_markup=turn_ui.get_back_to_group_markup(gc_link))

            if calculate_hand_score(current.cards) == 31.0:
                await handle_31_call(game, current)
                return

            await advance_turn(game, passed=False, last_action=action_desc)

        elif action == "call_confirm":
            if game.caller_id is not None:
                await callback.answer("🔒 CALL pehle hi ho chuka hai! Aap Call nahi kar sakte.", show_alert=True)
                return

            header = turn_ui.render_dm_cards_header(current.cards, game.table_cards)
            await callback.message.edit_text(
                f"{header}⚡ <b>Are you sure you want to CALL?</b>\nYour hand locks and others get ONE final turn.",
                reply_markup=turn_ui.get_action_confirmation_markup(chat_id, "call")
            )

        elif action == "call_yes":
            if game.caller_id is not None:
                await callback.answer("🔒 CALL pehle hi ho chuka hai!", show_alert=True)
                return

            game.caller_id = current.user_id
            database.update_stat(current.user_id, current.name, "calls")

            msg_text = turn_ui.render_move_locked_in(current.cards, "You called! Hand is locked.")
            await callback.message.edit_text(msg_text, reply_markup=turn_ui.get_back_to_group_markup(gc_link))
            action_desc = f"{current.name} called. Final turns begin."
            await advance_turn(game, passed=False, last_action=action_desc)

        elif action == "back":
            call_locked = (game.caller_id is not None)
            text = turn_ui.render_dm_hand_view(current.cards, game.table_cards)
            markup = turn_ui.get_dm_turn_buttons(chat_id, is_call_locked=call_locked)
            await callback.message.edit_text(text, reply_markup=markup)

# --- DUMMY WEB SERVER (RENDER FREE WEB SERVICE PORT SUPPORT) ---

async def dummy_health_check(request):
    return web.Response(text="Bot is running healthy!")

async def start_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    app = web.Application()
    app.router.add_get("/", dummy_health_check)
    app.router.add_get("/health", dummy_health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# --- ENTRY POINT ---

async def main():
    print("Deck Games Bot is starting...")

    commands = [
        BotCommand(command="start", description="Start / Launch a game"),
        BotCommand(command="deck", description="Open Games Menu Hub"),
        BotCommand(command="join", description="Join current game"),
        BotCommand(command="leave", description="Leave game / lobby"),
        BotCommand(command="remove", description="Start removal vote (reply)"),
        BotCommand(command="endgame", description="End active game"),
        BotCommand(command="profile", description="View personal stats"),
        BotCommand(command="leaderboard", description="View rankings"),
        BotCommand(command="rules", description="View game rules"),
        BotCommand(command="help", description="Show commands help")
    ]
    await bot.set_my_commands(commands)

    # Render health-check web server start
    await start_dummy_server()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, polling_timeout=15)

if __name__ == "__main__":
    asyncio.run(main())
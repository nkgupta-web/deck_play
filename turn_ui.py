from typing import List, Optional, Dict, Any
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from cards_and_scoring import Card, calculate_hand_score, format_score
from game_state import GameRoom, Player
import config

def format_cards_row(cards: List[Card]) -> str:
    return "  ".join(f"[{c.suit.value} {c.rank}]" for c in cards)

def get_lobby_markup(chat_id: int, bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Join Game", callback_data=f"lobby:join:{chat_id}"),
            InlineKeyboardButton(text="🚪 Leave", callback_data=f"lobby:leave:{chat_id}")
        ],
        [
            InlineKeyboardButton(text="📩 Enable Bot DM", url=f"https://t.me/{bot_username}?start=join")
        ],
        [
            InlineKeyboardButton(text="▶️ Start Game (Host)", callback_data=f"lobby:start:{chat_id}")
        ]
    ])

def render_lobby_view(game: GameRoom) -> str:
    lines = [
        "🎴 <b>CALL 31 — LOBBY</b>",
        "─────────────────────────",
        f"👑 Host: <b>{game.host_name}</b>\n",
        "<b>Players Joined:</b>"
    ]
    for idx, p in enumerate(game.players.values(), 1):
        lines.append(f"  {idx}. {p.name}")

    lines.append("─────────────────────────")
    lines.append(f"👥 <b>Total:</b> {len(game.players)}/{config.MAX_PLAYERS} (Min: {config.MIN_PLAYERS})")
    lines.append("<i>Host can start once 2 or more players join.</i>")
    return "\n".join(lines)

def get_group_turn_markup(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Open Hand in DM", url=f"https://t.me/{bot_username}")]
    ])

def render_group_turn_view(game: GameRoom, last_action_text: Optional[str] = None) -> str:
    table_str = format_cards_row(game.table_cards)
    current = game.current_player
    
    if current:
        curr_tag = f"<a href=\"tg://user?id={current.user_id}\">{current.name}</a>"
    else:
        curr_tag = "None"

    lives_lines = []
    for p in game.players.values():
        prefix = "👑 " if p.user_id == game.host_id else "• "
        if p.lives > 0 and p.is_active:
            status = "❤️" * p.lives + "🖤" * max(0, config.STARTING_LIVES - p.lives)
            lives_lines.append(f"{prefix}{p.name:<10} {status}")
        else:
            lives_lines.append(f"{prefix}{p.name:<10} 🖤🖤🖤 [OUT]")

    text_parts = [f"🎴 <b>CALL 31 • ROUND {game.round_number}</b>"]

    if game.caller_id is not None:
        caller = game.players.get(game.caller_id)
        c_name = caller.name if caller else "Player"
        caller_tag = f"<a href=\"tg://user?id={game.caller_id}\">{c_name}</a>"

        remaining_turns = sum(
            1 for p in game.active_players 
            if p.user_id != game.caller_id and not p.has_final_turn_taken
        )

        turn_word = "turn" if remaining_turns == 1 else "turns"
        text_parts.append(
            f"⚡ <b>CALL STATUS:</b> {caller_tag} called!\n"
            f"⏳ <b>{remaining_turns} {turn_word} left to reveal score</b>"
        )

    if last_action_text:
        text_parts.append(f"📢 <i>{last_action_text}</i>")

    text_parts.extend([
        "─────────────────────────",
        f"Cards on the table:\n{table_str}",
        "─────────────────────────",
        f"It is {curr_tag}'s turn now. ⏳ {config.TURN_TIME_SECONDS}s",
        "\n<b>LIVES:</b>\n" + "\n".join(lives_lines)
    ])
    return "\n".join(text_parts)

def render_dm_cards_header(cards: List[Card], table_cards: List[Card]) -> str:
    score = calculate_hand_score(cards)
    return (
        "Cards on the table:\n"
        f"<code>{format_cards_row(table_cards)}</code>\n\n"
        "Your hand:\n"
        f"<code>{format_cards_row(cards)}</code>\n\n"
        f"Current score: <b>{format_score(score)}</b>\n"
        "─────────────────────────\n"
    )

def render_dm_hand_view(cards: List[Card], table_cards: List[Card]) -> str:
    header = render_dm_cards_header(cards, table_cards)
    return (
        f"{header}"
        f"⏳ <i>Turn timer: {config.TURN_TIME_SECONDS}s</i>\n"
        "Choose your action:"
    )

def render_move_locked_in(cards: List[Card], action_summary: str) -> str:
    score = calculate_hand_score(cards)
    return (
        f"✅ <b>{action_summary}</b>\n"
        "Return to the group for the next turn.\n\n"
        "🃏 <b>Your latest hand:</b>\n"
        f"<code>{format_cards_row(cards)}</code>\n\n"
        f"Current score: <b>{format_score(score)}</b>"
    )

def get_dm_turn_buttons(chat_id: int, is_call_locked: bool = False, has_31: bool = False) -> InlineKeyboardMarkup:
    if is_call_locked:
        call_btn = InlineKeyboardButton(text="🔒 Call Locked", callback_data=f"turn:call_locked:{chat_id}")
    else:
        call_btn = InlineKeyboardButton(text="⚡ Call Hand", callback_data=f"turn:call_confirm:{chat_id}")

    if has_31:
        return InlineKeyboardMarkup(inline_keyboard=[
            [call_btn],
            [InlineKeyboardButton(text="⏭️ Pass / Skip", callback_data=f"turn:pass_confirm:{chat_id}")]
        ])

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Exchange 1 Card", callback_data=f"turn:ex1:{chat_id}")],
        [InlineKeyboardButton(text="🔁 Exchange All", callback_data=f"turn:exall_confirm:{chat_id}")],
        [InlineKeyboardButton(text="⏭️ Pass / Skip", callback_data=f"turn:pass_confirm:{chat_id}")],
        [call_btn]
    ])

def get_exchange_step1_markup(chat_id: int, player: Player) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=f"{c.suit.value} {c.rank}", callback_data=f"turn:swap_h:{chat_id}:{c.id}")
        for c in player.cards
    ]
    return InlineKeyboardMarkup(inline_keyboard=[
        buttons,
        [InlineKeyboardButton(text="⬅️ Cancel", callback_data=f"turn:back:{chat_id}")]
    ])

def get_exchange_step2_markup(chat_id: int, table_cards: List[Card], hand_card_id: str) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=f"{c.suit.value} {c.rank}", callback_data=f"turn:swap_t:{chat_id}:{hand_card_id}:{c.id}")
        for c in table_cards
    ]
    return InlineKeyboardMarkup(inline_keyboard=[
        buttons,
        [InlineKeyboardButton(text="⬅️ Back", callback_data=f"turn:ex1:{chat_id}")]
    ])

def get_action_confirmation_markup(chat_id: int, action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Confirm", callback_data=f"turn:{action}_yes:{chat_id}"),
            InlineKeyboardButton(text="❌ Cancel", callback_data=f"turn:back:{chat_id}")
        ]
    ])

def get_back_to_group_markup(group_link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↗️ Back to Group", url=group_link)]
    ])

# --- MULTI-GAME HUB SELECTION MARKUPS & TEMPLATES ---

def get_hub_selection_markup(category: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎴 Call 31", callback_data=f"hub_sel:{category}:call31")],
        [InlineKeyboardButton(text="🃏 Teen Patti (Coming Soon)", callback_data="hub:coming_soon")],
        [InlineKeyboardButton(text="♠️ Blackjack (Coming Soon)", callback_data="hub:coming_soon")]
    ])

def get_play_games_markup(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎴 Call 31", callback_data=f"hub:launch_31:{chat_id}")],
        [InlineKeyboardButton(text="🃏 Teen Patti (Coming Soon)", callback_data="hub:coming_soon")],
        [InlineKeyboardButton(text="♠️ Blackjack (Coming Soon)", callback_data="hub:coming_soon")]
    ])

def get_remove_vote_markup(chat_id: int, target_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🗳️ Vote to Remove (1/2)", callback_data=f"vote_rem:{chat_id}:{target_id}")
        ]
    ])

def get_endgame_vote_markup(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🛑 Vote to End Game (1/2)", callback_data=f"vote_end:{chat_id}")
        ]
    ])

def render_call31_rules() -> str:
    return (
        "📖 <b>CALL 31 — RULES & SCORING</b>\n"
        "─────────────────────────\n"
        "🎯 <b>Objective:</b>\n"
        "Build the highest hand value of 3 cards (Max: 31). The player with the lowest score loses 1 life ❤️!\n\n"
        "🃏 <b>Scoring System:</b>\n"
        "• Cards of the same suit (♠️/♥️/♦️/♣️) are summed together.\n"
        "• Ace (A) = 11 pts\n"
        "• Face Cards (K, Q, J, 10) = 10 pts\n"
        "• Numbers 2 to 9 = Face value\n"
        "• <b>Three of a Kind:</b> 3 cards of identical rank score a fixed <b>30.5 pts</b> regardless of suits!\n\n"
        "🕹️ <b>Turn Actions:</b>\n"
        "• 🔄 <b>Exchange 1:</b> Swap 1 hand card with 1 table card.\n"
        "• 🔁 <b>Exchange All:</b> Swap your entire hand with all 3 table cards.\n"
        "• ⏭️ <b>Pass / Skip:</b> Make no move (3 consecutive passes refresh table cards).\n"
        "• ⚡ <b>Call Hand:</b> Knock! Locks your hand while every other player gets one final turn.\n\n"
        "❤️ <b>Elimination:</b> Each player starts with 3 lives. 0 lives = OUT!"
    )

def render_call31_profile(data: Optional[Dict[str, Any]], user_name: str) -> str:
    if not data or data.get("games", 0) == 0:
        return (
            "🎴 <b>CALL 31 • PLAYER PROFILE</b>\n\n"
            f"👤 <b>{user_name}</b>\n\n"
            "<i>No games played yet!</i>"
        )

    return (
        "🎴 <b>CALL 31 • PLAYER PROFILE</b>\n\n"
        f"👤 <b>{data.get('name', user_name)}</b>\n\n"
        f"🎮 Games Played: <b>{data.get('games', 0)}</b>\n"
        f"🏆 Wins: <b>{data.get('wins', 0)}</b>\n"
        f"🤝 Joint Wins: <b>{data.get('joint_wins', 0)}</b>\n\n"
        f"🎯 Round Wins: <b>{data.get('round_wins', 0)}</b>\n"
        f"🛡️ Rounds Survived: <b>{data.get('rounds_survived', 0)}</b>\n\n"
        f"✨ Exact 31s: <b>{data.get('exact_31', 0)}</b>\n"
        f"⭐ Exact 30½: <b>{data.get('exact_30_5', 0)}</b>\n\n"
        f"🔥 Current Win Streak: <b>{data.get('current_streak', 0)}</b>\n"
        f"🏅 Best Win Streak: <b>{data.get('best_streak', 0)}</b>\n\n"
        f"🔄 1-Card Exchanges: <b>{data.get('ex_1', 0)}</b>\n"
        f"🔁 Full Hand Swaps: <b>{data.get('ex_all', 0)}</b>\n"
        f"⚡ Calls: <b>{data.get('calls', 0)}</b>\n"
        f"⏭️ Passes: <b>{data.get('passes', 0)}</b>\n\n"
        f"💔 Lives Lost: <b>{data.get('lives_lost', 0)}</b>"
    )

def render_call31_leaderboard(top_players: List[Dict[str, Any]], user_rank: int) -> str:
    lines = ["🏆 <b>CALL 31 • LEADERBOARD</b>\n"]
    medals = ["🥇", "🥈", "🥉"]

    if not top_players:
        lines.append("<i>Leaderboard is currently empty. Play to rank!</i>\n")
    else:
        for idx, p in enumerate(top_players, 1):
            badge = medals[idx - 1] if idx <= 3 else f"{idx}️⃣"
            j_wins = p.get('joint_wins', 0)
            lines.append(
                f"{badge} <b>{p['name']}</b>\n"
                f"   🏆 {p['wins']} Wins • 🤝 {j_wins} Joint • 🎮 {p['games']} Matches\n"
            )

    lines.append("──────────────────────────────")
    lines.append(f"Your Position: <b>#{user_rank}</b>")
    return "\n".join(lines)
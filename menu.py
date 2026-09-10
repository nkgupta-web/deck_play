from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_game_categories_markup(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎴 Play Call 31 (Survival)", callback_data=f"hub:launch_31:{chat_id}")
        ],
        [
            InlineKeyboardButton(text="🃏 Classic Rummy (Coming Soon)", callback_data="hub:coming_soon")
        ],
        [
            InlineKeyboardButton(text="ℹ️ Rules & Scoring", callback_data=f"hub:rules:{chat_id}")
        ]
    ])

def render_hub_welcome(group_name: str) -> str:
    return (
        f"🎮 <b>DECK GAMES HUB • {group_name}</b>\n"
        "─────────────────────────\n"
        "Game choose karke play button dabao:\n\n"
        "• <b>🎴 Call 31:</b> 2-11 Players | Fast-paced suit matching survival.\n"
        "• <b>🃏 Other Games:</b> Expandable deck collection.\n"
        "─────────────────────────\n"
        "<i>Click below to launch Call 31 lobby!</i>"
    )
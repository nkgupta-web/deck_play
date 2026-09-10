import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
import config
from cards_and_scoring import Card, build_deck

@dataclass
class Player:
    user_id: int
    name: str
    username: Optional[str] = None
    lives: int = config.STARTING_LIVES
    cards: List[Card] = field(default_factory=list)
    is_active: bool = True
    warning_count: int = 0
    has_final_turn_taken: bool = False

@dataclass
class GameRoom:
    chat_id: int
    host_id: int
    host_name: str
    status: str = "LOBBY"  # LOBBY, IN_PROGRESS, ENDED
    players: Dict[int, Player] = field(default_factory=dict)
    turn_order: List[int] = field(default_factory=list)
    current_turn_index: int = 0
    table_cards: List[Card] = field(default_factory=list)
    unused_deck: List[Card] = field(default_factory=list)
    consecutive_passes: int = 0
    caller_id: Optional[int] = None
    round_number: int = 1
    joining_open: bool = True
    first_life_lost: bool = False
    active_timer_task: Optional[asyncio.Task] = None

    # Voting systems
    active_remove_votes: Dict[int, Set[int]] = field(default_factory=dict)  # target_id -> set(voter_ids)
    endgame_votes: Set[int] = field(default_factory=set)  # set(voter_ids)

    @property
    def active_players(self) -> List[Player]:
        return [p for p in self.players.values() if p.is_active and p.lives > 0]

    @property
    def current_player(self) -> Optional[Player]:
        if not self.turn_order:
            return None
        uid = self.turn_order[self.current_turn_index]
        return self.players.get(uid)

    def reassign_host_if_needed(self) -> Optional[Player]:
        """Agar current host active nahi hai ya chala gaya, toh agle active player ko host banao."""
        curr_host = self.players.get(self.host_id)
        if not curr_host or not curr_host.is_active or curr_host.lives <= 0:
            for uid in self.turn_order:
                p = self.players.get(uid)
                if p and p.is_active and p.lives > 0:
                    self.host_id = p.user_id
                    self.host_name = p.name
                    return p
            # Agar turn order me na mile toh active players se pick karo
            active = self.active_players
            if active:
                self.host_id = active[0].user_id
                self.host_name = active[0].name
                return active[0]
        return None

# In-memory storage & locks
GAMES: Dict[int, GameRoom] = {}
_GAME_LOCKS: Dict[int, asyncio.Lock] = {}

def get_game_lock(chat_id: int) -> asyncio.Lock:
    if chat_id not in _GAME_LOCKS:
        _GAME_LOCKS[chat_id] = asyncio.Lock()
    return _GAME_LOCKS[chat_id]

def start_new_round(game: GameRoom):
    game.unused_deck = build_deck()
    game.table_cards = [game.unused_deck.pop(), game.unused_deck.pop(), game.unused_deck.pop()]
    game.consecutive_passes = 0
    game.caller_id = None

    # Sirf active surviving players ko cards deal karo
    for p in game.players.values():
        p.cards.clear()
        p.has_final_turn_taken = False
        p.warning_count = 0
        if p.is_active and p.lives > 0:
            p.cards = [game.unused_deck.pop(), game.unused_deck.pop(), game.unused_deck.pop()]

    # Turn order update karo
    game.turn_order = [p.user_id for p in game.active_players]
    game.current_turn_index = 0
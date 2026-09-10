from dataclasses import dataclass
from enum import Enum
import random
from typing import List

class Suit(str, Enum):
    SPADES = "♠"
    HEARTS = "♥"
    DIAMONDS = "♦"
    CLUBS = "♣"

RANKS = ["6", "7", "8", "9", "10", "J", "Q", "K", "A"]

RANK_VALUES = {
    "6": 6.0, "7": 7.0, "8": 8.0, "9": 9.0, "10": 10.0,
    "J": 10.0, "Q": 10.0, "K": 10.0, "A": 11.0
}

@dataclass(frozen=True)
class Card:
    rank: str
    suit: Suit

    @property
    def id(self) -> str:
        return f"{self.rank}-{self.suit.value}"

    @property
    def value(self) -> float:
        return RANK_VALUES[self.rank]

    def __str__(self) -> str:
        return f"{self.suit.value}{self.rank}"

    @classmethod
    def from_id(cls, card_id: str) -> "Card":
        parts = card_id.split("-")
        rank = parts[0]
        suit = Suit(parts[1])
        return cls(rank=rank, suit=suit)

def build_deck() -> List[Card]:
    """Generates exactly one pack of 36 cards (no duplicate copies)."""
    deck = []
    for suit in Suit:
        for rank in RANKS:
            deck.append(Card(rank=rank, suit=suit))
    random.shuffle(deck)
    return deck

def calculate_hand_score(cards: List[Card]) -> float:
    """Calculates deterministic score: 31 > 30.5 > highest same-suit sum."""
    if len(cards) != 3:
        return 0.0

    # 1. Check for 3 of a kind (Special 30.5)
    if cards[0].rank == cards[1].rank == cards[2].rank:
        return 30.5

    # 2. Check Suit Totals
    suit_totals = {}
    for c in cards:
        suit_totals[c.suit] = suit_totals.get(c.suit, 0.0) + c.value

    best_suit_score = max(suit_totals.values()) if suit_totals else 0.0
    return min(best_suit_score, 31.0)

def format_score(score: float) -> str:
    if score.is_integer():
        return str(int(score))
    return f"{score:.1f}"
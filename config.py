import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "8871468152:AAFTKdV0JYzdUekk7068datELzCxgOX6XBY")
BOT_USERNAME = os.getenv("BOT_USERNAME", "deckplaybot")
STARTING_LIVES = 3
MAX_PLAYERS = 11
MIN_PLAYERS = 2
TURN_TIME_SECONDS = 60
PASS_REFRESH_THRESHOLD = 3
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://neondb_owner:npg_JYhO0n7IyRSG@ep-lively-union-b5wrxa7e-pooler.c-7.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
)
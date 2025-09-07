import os

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple, Optional

import discord
from discord.ext import commands
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log = logging.getLogger("slot-bot")

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
CREDENTIALS_FILE = "credentials.json"
CACHE_DURATION_SECONDS = 300  # Cache Google Sheets data for 5 minutes

# --- Google Sheets Service ---
class GoogleSheetManager:
    """Handles all interactions with the Google Sheet, including caching."""

    def __init__(self, credentials_path: str, sheet_id: str):
        self.sheet_id = sheet_id
        self.scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        try:
            self.creds = Credentials.from_service_account_file(credentials_path, scopes=self.scopes)
            self.client = gspread.authorize(self.creds)
            self.sheet = self.client.open_by_key(self.sheet_id)
        except FileNotFoundError:
            log.error(f"Credentials file not found at '{credentials_path}'. Please ensure it exists.")
            self.client = None
        except Exception as e:
            log.error(f"Failed to authorize with Google Sheets: {e}")
            self.client = None

        self._schedule_cache: Optional[Dict[str, Any]] = None
        self._schedule_last_updated: Optional[datetime] = None
        self._bookers_cache: Optional[List[List[str]]] = None
        self._bookers_last_updated: Optional[datetime] = None

    def _is_cache_valid(self, last_updated: Optional[datetime]) -> bool:
        """Checks if the cache is still valid."""
        if not last_updated:
            return False
        return (datetime.now() - last_updated).total_seconds() < CACHE_DURATION_SECONDS

    def get_schedule(self) -> Optional[Dict[str, Any]]:
        """Fetches the schedule from the sheet, using a cache."""
        if self.client is None: return None

        if self._is_cache_valid(self._schedule_last_updated) and self._schedule_cache:
            log.info("Returning schedule from cache.")
            return self._schedule_cache

        log.info("Fetching fresh schedule data from Google Sheets.")
        try:
            worksheet = self.sheet.get_worksheet(5)
            all_values = worksheet.get_all_values(value_render_option='FORMATTED_VALUE')

            dates = all_values[5][2:9]  # Columns C–I in row 6
            schedule = {}

            for row in all_values[6:]:
                time = row[1]  # Column B
                if not time:
                    break

                schedule[time] = {
                    date: value if value else "NOT BOOKED"
                    for date, value in zip(dates, row[2:9])
                }
            
            self._schedule_cache = schedule
            self._schedule_last_updated = datetime.now()
            return self._schedule_cache
        except gspread.exceptions.APIError as e:
            log.error(f"GSpread API Error while fetching schedule: {e}")
            return None
        except Exception as e:
            log.error(f"An unexpected error occurred while fetching schedule: {e}")
            return None


    def get_bookers(self) -> Optional[List[List[str]]]:
        """Fetches the list of bookers from the sheet, using a cache."""
        if self.client is None: return None

        if self._is_cache_valid(self._bookers_last_updated) and self._bookers_cache:
            log.info("Returning bookers from cache.")
            return self._bookers_cache

        log.info("Fetching fresh bookers data from Google Sheets.")
        try:
            worksheet = self.sheet.get_worksheet(0)
            all_values = worksheet.get_all_values()
            
            bookers = [row[0:2] for row in all_values[1:9]]

            self._bookers_cache = bookers
            self._bookers_last_updated = datetime.now()
            return self._bookers_cache
        except gspread.exceptions.APIError as e:
            log.error(f"GSpread API Error while fetching bookers: {e}")
            return None
        except Exception as e:
            log.error(f"An unexpected error occurred while fetching bookers: {e}")
            return None


# --- Bot Implementation ---
class MyBot(commands.Bot):
    def __init__(self, sheet_manager: GoogleSheetManager):
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.sheet_manager = sheet_manager

    async def on_ready(self):
        log.info(f'Logged in as {self.user} (ID: {self.user.id})')
        log.info('Syncing commands to the global command tree...')
        try:
            synced = await self.tree.sync()
            log.info(f"Synced {len(synced)} commands.")
        except Exception as e:
            log.error(f"Failed to sync commands: {e}")

    async def setup_hook(self):
        log.info("Bot is starting up...")

# --- Bot Setup ---
if not TOKEN:
    log.critical("FATAL: DISCORD_TOKEN environment variable not set.")
else:
    sheet_manager = GoogleSheetManager(CREDENTIALS_FILE, SHEET_ID)
    bot = MyBot(sheet_manager)

    @bot.tree.command(name="bookers", description="Show who's responsible for booking PI.")
    async def bookers(interaction: discord.Interaction):
        """Displays the current assignments in an embed."""
        await interaction.response.defer(ephemeral=True)
        
        data = bot.sheet_manager.get_bookers()
        if data is None:
            await interaction.followup.send("Sorry, I couldn't fetch data from Google Sheets right now. Please try again later.", ephemeral=True)
            return
        if not data:
            await interaction.followup.send("There are no assignments to show.", ephemeral=True)
            return

        embed = discord.Embed(
            title="📋 Current Bookers",
            description="Status of all available time slots.",
            color=discord.Color.blue()
        )

        for time, name in data:
            is_booked = bool(name.strip())
            status_emoji = "✅" if is_booked else "❌"
            display_name = name if is_booked else "Not Assigned"
            embed.add_field(name=f"{status_emoji} {time}", value=display_name, inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.command(name="bookings", description="Check the status of the current PI booking")
    async def bookings(interaction: discord.Interaction):
        """Checks if the current time slot is booked and for how long."""
        await interaction.response.defer(ephemeral=True)
        
        schedule = bot.sheet_manager.get_schedule()
        if schedule is None:
            await interaction.followup.send("Sorry, I couldn't fetch the schedule from Google Sheets. Please try again later.", ephemeral=True)
            return

        now = datetime.now()
        today_str = now.strftime("%#m/%#d/%Y")

        # Round down to the nearest 30-minute mark
        rounded_minute = 0 if now.minute < 30 else 30
        current_slot_dt = now.replace(minute=rounded_minute, second=0, microsecond=0)
        
        # Format time key for dictionary lookup (e.g., "8:30 am")
        current_time_key = current_slot_dt.strftime("%#I:%M %p").lower()
        
        current_status = schedule.get(current_time_key, {}).get(today_str, "NOT BOOKED")

        if current_status != "BOOKED":
            await interaction.followup.send(f"The current slot ({current_time_key}) is **{current_status}** ❌.", ephemeral=True)
            return

        # If booked, find the end time by checking subsequent slots
        end_time_dt = current_slot_dt
        while True:
            end_time_dt += timedelta(minutes=30)
            next_day_str = end_time_dt.strftime("%#m/%#d/%Y")
            next_time_key = end_time_dt.strftime("%#I:%M %p").lower()
            
            next_status = schedule.get(next_time_key, {}).get(next_day_str, "NOT BOOKED")
            
            if next_status != "BOOKED":
                end_time_str = end_time_dt.strftime("%#I:%M %p").lower()
                break
        
        await interaction.followup.send(
            f"The current slot ({current_time_key}) is **BOOKED** until **{end_time_str}** ✅. Happy Studying!",
            ephemeral=True
        )

    bot.run(TOKEN)

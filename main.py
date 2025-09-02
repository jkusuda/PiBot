import os
import json
import logging
from pathlib import Path
from typing import Dict, Any

import discord
from discord import app_commands
from discord.ui import View, Select
from discord import SelectOption
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Config / Logging 
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("slot-bot")

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("api_key")

DATA_FILE = Path("data.json")
if not DATA_FILE.exists() or DATA_FILE.stat().st_size == 0:
    DATA_FILE.write_text(json.dumps({}, indent=4))

# Data manager
class DataManager:
    def __init__(self, path: Path):
        self.path = path

    def _read(self) -> Dict[str, Any]:
        try:
            return json.loads(self.path.read_text())
        except Exception:
            log.exception("Failed to read data file, returning empty dict.")
            return {}

    def _write(self, data: Dict[str, Any]) -> None:
        try:
            self.path.write_text(json.dumps(data, indent=4))
        except Exception:
            log.exception("Failed to write data file.")

    def assign_slot(self, user_id: str, slot_time: str) -> None:
        data = self._read()
        data[user_id] = {"time": slot_time, "booked": False}
        self._write(data)

    def mark_booked(self, user_id: str) -> bool:
        data = self._read()
        if user_id in data:
            data[user_id]["booked"] = True
            self._write(data)
            return True
        return False

    def get_assignments(self) -> Dict[str, Any]:
        return self._read()

data_mgr = DataManager(DATA_FILE)

# UI: Select + View
class TimeSelect(Select):
    def __init__(self, target_user: discord.User, data_mgr: DataManager):
        options = [
            SelectOption(label="09:00", description="9 AM slot", value="09:00"),
            SelectOption(label="11:00", description="11 AM slot", value="11:00"),
            SelectOption(label="14:00", description="2 PM slot", value="14:00"),
            SelectOption(label="16:00", description="4 PM slot", value="16:00"),
        ]
        super().__init__(
            placeholder="Select a time slot",
            min_values=1,
            max_values=1,
            options=options
        )
        self.target_user = target_user
        self.data_mgr = data_mgr

    async def callback(self, interaction: discord.Interaction):
        selected_time = self.values[0]
        try:
            self.data_mgr.assign_slot(str(self.target_user.id), selected_time)
        except Exception:
            log.exception("Error assigning slot")
            await interaction.response.send_message("❌ Failed to save assignment.", ephemeral=True)
            return

        try:
            await self.target_user.send(f"📅 You were assigned a slot at **{selected_time}** by {interaction.user}.")
        except Exception:
            pass

        await interaction.response.send_message(
            f"✅ Assigned {self.target_user.mention} to **{selected_time}**.",
            ephemeral=True
        )

        if self.view:
            self.view.stop()

class TimeSelectView(View):
    def __init__(self, target_user: discord.User, data_mgr: DataManager, timeout: float = 60.0):
        super().__init__(timeout=timeout)
        self.add_item(TimeSelect(target_user, data_mgr))

# Bot Setup
intents = discord.Intents.default()
intents.members = True

class SlotClient(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.scheduler = AsyncIOScheduler()

    async def setup_hook(self):
        await self.tree.sync()
        self.scheduler.start()
        self.scheduler.add_job(self.reminder_1155, 'cron', hour=23, minute=3)
        self.scheduler.add_job(self.reminder_1200, 'cron', hour=0, minute=0)
        self.scheduler.add_job(self.reminder_900, 'cron', hour=9, minute=0)

    async def send_reminder(self, only_unbooked: bool = False, include_markbook_instruction: bool = False):
        BOOKING_SITE = "https://libcal.uflib.ufl.edu/space/28257"
        SPREADSHEET = "https://docs.google.com/spreadsheets/d/15N-sULElmb4B3t1UEnwiZQCUpnQ9iKcJrBbBF2URRaU/"

        data = data_mgr.get_assignments()
        for uid, info in data.items():
            if only_unbooked and info.get("booked", False):
                continue

            try:
                user = await self.fetch_user(int(uid))
                booked = info.get("booked", False)
                color = discord.Color.green() if booked else discord.Color.blue()

                embed = discord.Embed(
                    title="⏰ Slot Reminder",
                    description="Here are your slot details:",
                    color=color
                )
                embed.add_field(name="Time", value=info.get("time", "N/A"), inline=False)
                embed.add_field(name="Status", value="✅ Booked" if booked else "❌ Not booked", inline=False)
                embed.add_field(name="Booking Site", value=f"[Click here to book]({BOOKING_SITE})", inline=False)

                if include_markbook_instruction:
                    embed.add_field(
                        name="Next Steps",
                        value=f"Remember to mark your time as booked using the `/markbooked` command "
                              f"and update the [spreadsheet]({SPREADSHEET}).",
                        inline=False
                    )

                await user.send(embed=embed)

            except Exception as e:
                log.warning(f"Failed to DM {uid}: {e}")

    async def reminder_1155(self):
        await self.send_reminder(only_unbooked=False, include_markbook_instruction=False)

    async def reminder_1200(self):
        await self.send_reminder(only_unbooked=False, include_markbook_instruction=True)

    async def reminder_900(self):
        await self.send_reminder(only_unbooked=True, include_markbook_instruction=True)

client = SlotClient(intents=intents)

# Commands
@client.tree.command(name="assignslot", description="Assign a time slot to a user")
async def assignslot(interaction: discord.Interaction, user: discord.User):
    view = TimeSelectView(user, data_mgr, timeout=60.0)
    await interaction.response.send_message(
        f"Select a time slot for {user.mention}:",
        view=view,
        ephemeral=True
    )

@client.tree.command(name="markbooked", description="Mark a user's slot as booked")
async def markbooked(interaction: discord.Interaction, user: discord.User):
    success = data_mgr.mark_booked(str(user.id))
    if success:
        await interaction.response.send_message(f"✅ Marked {user.mention}'s slot as booked", ephemeral=True)
    else:
        await interaction.response.send_message(f"⚠️ No slot found for {user.mention}", ephemeral=True)

@client.tree.command(name="showassignments", description="Show all assignments")
async def showassignments(interaction: discord.Interaction):
    data = data_mgr.get_assignments()
    if not data:
        await interaction.response.send_message("No assignments yet.", ephemeral=True)
        return

    embed = discord.Embed(
        title="📋 Current Assignments",
        color=discord.Color.blurple()
    )
    for uid, info in data.items():
        booked_status = "✅ Booked" if info.get("booked") else "❌ Not booked"
        try:
            user = await client.fetch_user(int(uid))
            embed.add_field(name=str(user), value=f"{info.get('time')} ({booked_status})", inline=False)
        except Exception:
            embed.add_field(name=f"User ID {uid}", value=f"{info.get('time')} ({booked_status})", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

if not TOKEN:
    log.critical("No bot token found. Set DISCORD_TOKEN or api_key in your environment.")
else:
    client.run(TOKEN)

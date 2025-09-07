# basic sheets tests

import gspread
from google.oauth2.service_account import Credentials

scopes = [
    "https://www.googleapis.com/auth/spreadsheets"
]

creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
client = gspread.authorize(creds)

sheet_id = "1Y71XIF2NZleECWCM-USnaBsSPsMshlpKfWKDK5QGz3A"

sheet = client.open_by_key(sheet_id)

worksheet = sheet.get_worksheet(5)

# --- Fetch all values as displayed in sheet ---
all_values = worksheet.get_all_values(value_render_option='FORMATTED_VALUE')  # keeps formatted strings

# --- Date headers (row 6 → index 5) ---
dates = all_values[5][2:9]  # columns C–I

# --- Build dictionary ---
schedule = {}

for row in all_values[6:]:  # rows 7+ in Sheets
    time = row[1]  # column B
    if not time:
        break

    schedule[time] = {}
    for date, value in zip(dates, row[2:9]):  # columns C–I
        if value == "":
            value = "NOT BOOKED"
        schedule[time][date] = value  # "BOOKED" / "NOT BOOKED"

# --- Example usage ---
print("All dates:", dates)
print("8:00 am on 9/18/2025:", schedule["8:00 am"]["9/18/2025"])
print("8:30 am on 9/18/2025:", schedule["8:30 am"]["9/18/2025"])
print("9:00 am on 9/18/2025:", schedule["9:00 am"]["9/18/2025"])

booking_info = sheet.get_worksheet(0)
all_values = booking_info.get_all_values()
bookers = []
for row in all_values[1:9]:
    bookers.append(row[0:2])


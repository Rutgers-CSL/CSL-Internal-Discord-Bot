import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

# Connect to Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_file("csl-bot-test-050b55de7696.json", scopes=scope)
client = gspread.authorize(creds)
sheet = client.open("CSL F26 Shift Signups - TEMPLATE").worksheet("Schedule")

# CSL Maps day of week to BOTH sub-column indices in the sheet
DAY_TO_COL = {
    "Monday": (3, 4),
    "Tuesday": (5, 6),
    "Wednesday": (7, 8),
    "Thursday": (9, 10),
    "Friday": (11, 12)
}

# CSL time slots and their row index in the sheet
TIME_SLOTS = [
    ("10:00", "11:30", 4),
    ("11:30", "13:00", 5),
    ("13:00", "15:00", 6),
    ("15:00", "17:00", 7),
    ("17:00", "19:00", 8),
    ("19:00", "21:00", 9),
    ("21:00", "23:00", 10),
]

# Hackerspace time slots and row indices
HACKERSPACE_TIME_SLOTS = [
    ("13:00", "15:00", 14),
    ("15:00", "17:00", 15),
]

# Hackerspace day to column mapping (single column per day)
HACKERSPACE_DAY_TO_COL = {
    "Monday": 3,
    "Tuesday": 5,
    "Wednesday": 7,
    "Thursday": 9,
    "Friday": 11
}

def get_current_shift(test_day=None, test_time=None):
    now = datetime.now()
    day = test_day if test_day else now.strftime("%A")
    current_time = test_time if test_time else now.strftime("%H:%M")

    cols = DAY_TO_COL.get(day)
    if not cols:
        return []

    names = []
    for start, end, row in TIME_SLOTS:
        if start <= current_time < end:
            for col in cols:
                cell_val = sheet.cell(row, col).value
                if cell_val and cell_val.strip() and cell_val.strip().lower() != "x":
                    names.append(cell_val.strip())
            return names
    
    return []

def get_current_hackerspace_shift(test_day=None, test_time=None):
    now = datetime.now()
    day = test_day if test_day else now.strftime("%A")
    current_time = test_time if test_time else now.strftime("%H:%M")

    col = HACKERSPACE_DAY_TO_COL.get(day)
    if not col:
        return None

    for start, end, row in HACKERSPACE_TIME_SLOTS:
        if start <= current_time < end:
            name = sheet.cell(row, col).value
            if name and name.strip() and name.strip().lower() != "x":
                return name.strip()
    
    return None

if __name__ == "__main__":
    print("CSL:", get_current_shift(test_day="Monday", test_time="13:00"))
    print("Hackerspace:", get_current_hackerspace_shift(test_day="Monday", test_time="13:00"))
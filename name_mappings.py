import json
import os
import threading

# .env can override this; defaults to a file alongside the bot.
MAPPINGS_FILE = os.getenv("MAPPINGS_FILE", "mappings.json")

# Guards read-modify-write so two people registering at the same moment
# can't clobber each other's entry.
_mapping_lock = threading.Lock()


def load_mappings():
    """Returns the full {discord_id_str: name} dict. Empty dict if no file yet."""
    if not os.path.exists(MAPPINGS_FILE):
        return {}
    with open(MAPPINGS_FILE, "r") as f:
        return json.load(f)


def save_mappings(mappings):
    with open(MAPPINGS_FILE, "w") as f:
        json.dump(mappings, f, indent=2)


def get_assignee_name(discord_id):
    """Returns the registered name for this Discord user, or None if unregistered."""
    mappings = load_mappings()
    return mappings.get(str(discord_id))


def set_assignee_name(discord_id, name):
    """Adds or updates the mapping for this Discord user."""
    with _mapping_lock:
        mappings = load_mappings()
        mappings[str(discord_id)] = name
        save_mappings(mappings)
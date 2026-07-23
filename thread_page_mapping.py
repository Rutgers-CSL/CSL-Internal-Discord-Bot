import json
import os

MAP_FILE = os.path.join(os.path.dirname(__file__), "thread_to_page.json")

def load_thread_map():
    if not os.path.exists(MAP_FILE):
        return {}
    with open(MAP_FILE, "r") as f:
        return json.load(f)

def save_thread_map(mapping):
    with open(MAP_FILE, "w") as f:
        json.dump(mapping, f, indent=2)

def get_page_id_for_thread(thread_id):
    mapping = load_thread_map()
    return mapping.get(str(thread_id))

def set_page_id_for_thread(thread_id, page_id):
    mapping = load_thread_map()
    mapping[str(thread_id)] = page_id
    save_thread_map(mapping)

def delete_thread_mapping(thread_id):
    mapping = load_thread_map()
    mapping.pop(str(thread_id), None)
    save_thread_map(mapping)
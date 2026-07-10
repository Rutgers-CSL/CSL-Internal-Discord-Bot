import discord
from discord.ext import commands, tasks
import logging
from dotenv import load_dotenv
from datetime import datetime
from notion_client import Client
import os

load_dotenv()

notion = Client(auth=os.getenv("NOTION_TOKEN"))
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

def get_data_source_id():
    db = notion.databases.retrieve(database_id=DATABASE_ID)
    return db["data_sources"][0]["id"]

def get_calendar_entries():
    DATA_SOURCE_ID = get_data_source_id()
    response = notion.data_sources.query(
    data_source_id=DATA_SOURCE_ID
)
    return response["results"]




if __name__ == "__main__":
        entries = get_calendar_entries()  # or no await if it's sync
        print(entries)

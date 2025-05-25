import os
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import time, timezone, timedelta
import requests
from bs4 import BeautifulSoup

import sqlite3
import asyncio

DATABASE_NAME = "alpaca.db"

def get_alpacahack_solves(user):
    response = requests.get(f"https://alpacahack.com/users/{user}")
    soup = BeautifulSoup(response.content, features="html.parser")
    tbody = soup.find("tbody", class_="MuiTableBody-root")
    ret = "```\n"
    ret += f"{user}\n"
    ret += f"{'CHALLENGE':20}{'SOLVES':20}{'SOLVED AT':20}\n"
    for i in tbody.find_all("tr"):
        data = i.find_all("td")
        challenge = data[0].find("a").text
        solves = data[1].find("p").text
        solve_at = data[2].find("p").text
        ret += f"{challenge:20}{solves:20}{solve_at:20}\n"
    ret += "```"
    return ret

# database 
def create_alpacahack_user_table_if_not_exists(conn: sqlite3.Connection):
    cursor = conn.cursor()
    cursor.execute('''
CREATE TABLE IF NOT EXISTS alpacahack_user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL
)
    ''')
    conn.commit()

def insert_alpacahack_user(conn: sqlite3.Connection, name:str):

    rstr = ""
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO alpacahack_user (name) VALUES (?)", (name, ))
        conn.commit()
        rstr = f"User '{name}' added."
    except sqlite3.IntegrityError as e:
        rstr = f"Insert error: {e}"
    return rstr


def delete_alpacahack_user(conn: sqlite3.Connection, name:str):
    rstr = ""
    cursor = conn.cursor()
    cursor.execute('DELETE FROM alpacahack_user WHERE name=?', (name,))
    if cursor.rowcount == 0:
        rstr = f"No user : {name}"
    else:
        rstr = f"Deleted user: {name}"
    conn.commit()
    return rstr


def get_all_alpacahack_users(conn: sqlite3.Connection):
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM alpacahack_user")
    return cursor.fetchall()


class Alpacahack(commands.Cog):
    JST = timezone(timedelta(hours=+9), "JST")

    def __init__(self, bot):
        with sqlite3.connect(DATABASE_NAME) as conn:
            create_alpacahack_user_table_if_not_exists(conn) # もしなければ作成する
        load_dotenv()
        self.bot = bot
        self.channel_id = int(os.getenv("BOT_CHANNEL_ID") or "0")
        self.alpacahack_solves.start()

    @tasks.loop(time=[time(hour=23, minute=00, tzinfo=JST)])
    async def alpacahack_solves(self):
        channel = self.bot.get_channel(self.channel_id)
        if channel is not None:
            try:
                with sqlite3.connect(DATABASE_NAME) as conn:
                    for i in get_all_alpacahack_users(conn):
                        await channel.send(get_alpacahack_solves(i[0]))
            except discord.DiscordException as e:
                print(f"Failed to send message: {e}")
        else:
            print("Channel not found. Check the channel ID.")

    @commands.command()
    async def add_alpaca(self, ctx, name:str):
        rstr = ""
        with sqlite3.connect(DATABASE_NAME) as conn:
            rstr += insert_alpacahack_user(conn, name) 
        await ctx.send(rstr)

    @commands.command()
    async def del_alpaca(self, ctx, name:str):
        rstr = ""
        with sqlite3.connect(DATABASE_NAME) as conn:
            rstr += delete_alpacahack_user(conn, name)
        await ctx.send(rstr)

    @commands.command()
    async def show_alpaca(self, ctx):
        with sqlite3.connect(DATABASE_NAME) as conn:
            fetched_alpaca_user_list = get_all_alpacahack_users(conn)
            if len(fetched_alpaca_user_list) == 0:
                await ctx.send("誰も登録されていません")
            else:
                rstr = "```"
                for i in fetched_alpaca_user_list:
                    rstr += i[0] + "\n"
                rstr += "```"
                await ctx.send(rstr)

    @commands.command()
    async def show_alpaca_score(self, ctx):
        try:
            with sqlite3.connect(DATABASE_NAME) as conn:
                for i in get_all_alpacahack_users(conn):
                    await ctx.send(get_alpacahack_solves(i[0]))
                    await asyncio.sleep(1)
        except discord.DiscordException as e:
            print(f"Failed to send message: {e}")


async def setup(bot):
    await bot.add_cog(Alpacahack(bot))

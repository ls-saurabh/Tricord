import os
import re
import logging
import asyncio
from datetime import datetime
from typing import Dict, Optional
import discord
from discord.ext import commands
import aiohttp
from discord import app_commands

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('SocialSearchBot')

class SearchBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            command_prefix=commands.when_mentioned_or('!'),
            intents=intents,
            help_command=None
        )

        self.platforms = {
            'facebook': {'url': 'https://facebook.com/', 'regex': r'^[a-zA-Z0-9.]+$'},
            'twitter': {'url': 'https://twitter.com/', 'regex': r'^[A-Za-z0-9_]{1,15}$'},
            'instagram': {'url': 'https://instagram.com/', 'regex': r'^[A-Za-z0-9_.]{1,30}$'},
            'linkedin': {'url': 'https://linkedin.com/in/', 'regex': r'^[a-zA-Z0-9-]{5,30}$'},
            'github': {'url': 'https://github.com/', 'regex': r'^[a-zA-Z0-9-]{1,39}$'},
            'youtube': {'url': 'https://youtube.com/@', 'regex': r'^[a-zA-Z0-9-]{3,30}$'},
            'twitch': {'url': 'https://twitch.tv/', 'regex': r'^[a-zA-Z0-9_]{4,25}$'},
            'tiktok': {'url': 'https://tiktok.com/@', 'regex': r'^[a-zA-Z0-9_.]{2,24}$'},
            'reddit': {'url': 'https://reddit.com/user/', 'regex': r'^[a-zA-Z0-9_-]{3,20}$'},
        }

        self.search_count = 0
        self.start_time = datetime.now()
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={'User-Agent': 'Mozilla/5.0 (compatible; SocialSearchBot/2.0)'},
                timeout=aiohttp.ClientTimeout(total=15)
            )
        return self._session

    async def setup_hook(self):
        await self.add_cog(SearchCog(self))
        await self.add_cog(StatsCog(self))
        await self.add_cog(HelpCog(self))
        await self.tree.sync()

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
        await super().close()

class SearchCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cache = {}
        self.cache_ttl = 3600  # 1 hour cache

    async def check_platform(self, platform: str, username: str) -> Optional[bool]:
        cache_key = (platform, username)
        current_time = datetime.now().timestamp()
        
        # Check cache first
        if cache_key in self.cache:
            cached_time, available = self.cache[cache_key]
            if current_time - cached_time < self.cache_ttl:
                return available

        try:
            # Platform-specific checks
            if platform == 'github':
                async with self.bot.session.get(
                    f'https://api.github.com/users/{username}'
                ) as response:
                    available = response.status == 404
            elif platform == 'instagram':
                async with self.bot.session.get(
                    f'https://www.instagram.com/{username}/',
                    allow_redirects=False
                ) as response:
                    available = response.status in (404, 302)
            else:
                async with self.bot.session.get(
                    self.bot.platforms[platform]['url'] + username,
                    allow_redirects=False
                ) as response:
                    available = response.status == 404
            
            # Update cache
            self.cache[cache_key] = (current_time, available)
            return available
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error(f"Error checking {platform}: {str(e)}")
            return None

    @commands.hybrid_command(name='search', description='Search for a name across social media')
    @commands.cooldown(1, 15, commands.BucketType.user)
    async def name_search(self, ctx: commands.Context, *, name: str):
        """Search for a name across multiple platforms"""
        self.bot.search_count += 1
        await ctx.defer()
        
        embed = discord.Embed(
            title=f"🔍 Search Results for {name}",
            color=discord.Color.blue()
        )
        
        # Add Google search
        embed.add_field(
            name="Google Search",
            value=f"[Search on Google](https://www.google.com/search?q={name.replace(' ', '+')})",
            inline=False
        )
        
        # Add platform links
        for platform, data in self.bot.platforms.items():
            profile_url = f"{data['url']}{name.replace(' ', '')}"
            embed.add_field(
                name=platform.capitalize(),
                value=f"[View Profile]({profile_url})",
                inline=True
            )
        
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='check', description='Check username availability')
    @app_commands.describe(username="The username to check")
    @commands.cooldown(1, 20, commands.BucketType.user)
    async def username_check(self, ctx: commands.Context, *, username: str):
        """Check username availability across platforms"""
        self.bot.search_count += 1
        await ctx.defer()

        # Validate username format
        invalid_platforms = [
            platform for platform, data in self.bot.platforms.items()
            if not re.fullmatch(data['regex'], username)
        ]

        if invalid_platforms:
            await ctx.send(
                f"⚠️ Username doesn't meet requirements for: {', '.join(invalid_platforms).title()}"
            )

        embed = discord.Embed(
            title=f"Username Availability: {username}",
            color=discord.Color.green()
        )

        results = {}
        for platform in self.bot.platforms:
            results[platform] = await self.check_platform(platform, username)

        # Split results into chunks for multiple embeds
        chunk_size = 6
        platforms = list(self.bot.platforms.keys())
        for i in range(0, len(platforms), chunk_size):
            chunk = platforms[i:i+chunk_size]
            embed = discord.Embed(color=discord.Color.green()) if i > 0 else embed
            
            for platform in chunk:
                available = results[platform]
                status = "✅ Available" if available else "❌ Taken" if available is False else "⚠️ Error"
                embed.add_field(
                    name=platform.capitalize(),
                    value=f"{status}\n[Check]({self.bot.platforms[platform]['url']}{username})",
                    inline=True
                )
            
            await ctx.send(embed=embed) if i > 0 else None

        await ctx.send(embed=embed)

class StatsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name='stats', description='Show bot statistics')
    async def show_stats(self, ctx: commands.Context):
        """Show bot usage statistics"""
        uptime = datetime.now() - self.bot.start_time
        embed = discord.Embed(
            title="📊 Bot Statistics",
            color=discord.Color.blue()
        )
        embed.add_field(name="Total Searches", value=self.bot.search_count)
        embed.add_field(name="Uptime", value=str(uptime).split('.')[0])
        embed.add_field(name="Servers", value=len(self.bot.guilds))
        await ctx.send(embed=embed)

class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name='help', description='Show help information')
    async def show_help(self, ctx: commands.Context):
        """Show help menu"""
        embed = discord.Embed(
            title="🆘 Social Search Bot Help",
            description="A bot to search usernames across social media platforms",
            color=discord.Color.blue()
        )
        
        commands_list = [
            ("!search <name>", "Search for a name across social media"),
            ("!check <username>", "Check username availability"),
            ("!stats", "Show bot statistics"),
            ("!help", "Show this help message")
        ]
        
        for cmd, desc in commands_list:
            embed.add_field(name=cmd, value=desc, inline=False)
        
        embed.set_footer(text="Support: https://discord.gg/example")
        await ctx.send(embed=embed)

async def main():
    bot = SearchBot()
    token = os.getenv("DISCORD_BOT_TOKEN")
    
    if not token:
        logger.error("DISCORD_BOT_TOKEN environment variable not set!")
        return
    
    async with bot:
        await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())

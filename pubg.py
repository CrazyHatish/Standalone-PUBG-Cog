import discord
from discord.ext import commands
from cogs.utils import checks
from cogs.utils.dataIO import dataIO
import asyncio
import logging
import os
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime


log = logging.getLogger("red.admin")


class PUBG:
    """PUBG bot"""

    def __init__(self, bot):
        self.bot = bot
        self._announce_msg = None
        self._announce_server = None
        self._data = dataIO.load_json('data/pubg/data.json')
        self._settings = dataIO.load_json('data/pubg/settings.json')
        self._settable_roles = self._settings.get("ROLES", {})

    def _save_settings(self):
        dataIO.save_json('data/pubg/settings.json', self._settings)

    def _save_data(self):
        dataIO.save_json('data/pubg/data.json', self._data)

    def _role_from_string(self, server, rolename, roles=None):
        if roles is None:
            roles = server.roles

        roles = [r for r in roles if r is not None]
        role = discord.utils.find(lambda r: r.name.lower() == rolename.lower(),
                                  roles)
        try:
            log.debug("Role {} found from rolename {}".format(
                    role.name, rolename))
        except Exception:
            log.debug("Role not found for rolename {}".format(rolename))

        return role

    async def _addrole(self, ctx, rolename, user: discord.Member = None):
        """Adds a role to a user, defaults to author

        Role name must be in quotes if there are spaces."""
        author = ctx.message.author
        channel = ctx.message.channel
        server = ctx.message.server

        if user is None:
            user = author

        role = self._role_from_string(server, rolename)

        if role is None:
            await self.bot.say('That role cannot be found.')
            return

        if not channel.permissions_for(server.me).manage_roles:
            await self.bot.say('I don\'t have manage_roles.')
            return

        await self.bot.add_roles(user, role)
        message = await self.bot.say('`Cargo {} adicionado a {}`'.format(role.name, user.name))
        await asyncio.sleep(2)
        await self.bot.delete_message(message)

    async def _set_roles(self, ctx, user):
        role_list = []
        ranks = []

        for m in ["duo", "solo", "squad"]:
            for v in ["fpp", "tpp"]:
                ranks.append(int(self._data[user.id]["stats"][m][v]["rating"]))

        rank = max(ranks)
        if rank > 0:
            if rank <= 1500:
                role_list.append(self._settable_roles[-1])
            elif 1500 < rank <= 1800:
                role_list.append(self._settable_roles[-2])
            elif 1800 < rank <= 2000:
                role_list.append(self._settable_roles[-3])
            elif 2000 < rank <= 2200:
                role_list.append(self._settable_roles[-4])
            elif 2200 < rank <= 2300:
                role_list.append(self._settable_roles[-5])
            else:
                role_list.append(self._settable_roles[-6])

        for role in role_list:
            await self._addrole(ctx, role, user)

    async def _removeroles(self, user):
        for role in user.roles:
            if role.name in self._settable_roles:
                await self.bot.remove_roles(user, role)

    async def _update(self, user, regions=None):
        s = requests.Session()

        try:
            url = f"https://dak.gg/profile/{self._data[user]['account']}"
        except KeyError:
            message = await self.bot.say("`Esse usuário ainda não está registrado`")
            await asyncio.sleep(10)
            await self.bot.delete_message(message)
            return 1

        r = s.get(url)
        renew_url = url + "/renew"

        soup = BeautifulSoup(r.content, 'lxml')
        token = soup.find("meta", {"name": "csrf-token"})

        headers = {
            "X-CSRF-TOKEN": token["content"],
            "X-Requested-With": "XMLHttpRequest",
        }

        if regions is None:
            regions = [soup.find("li", class_="active").find("a")["href"][-3:].strip("/")]
            if regions == ["rjp"]:
                regions = ["krjp"]

        for region in regions:
            _ = s.post(renew_url, headers=headers, data={"region": region})

        r = s.get(url)

        soup = BeautifulSoup(r.content, 'lxml')
        stats_list = ("rating", "kd", "winratio", "top10s", "deals", "games",
                      "mostkills", "headshots", "longest", "survival")
        modes = {mode: {"tpp": dict.fromkeys(stats_list), "fpp": dict.fromkeys(stats_list)}
                 for mode in ["squad", "solo", "duo"]}

        try:
            for mode, views in modes.items():
                section = soup.find("section", class_=f"{mode} modeItem")
                for view, stats in views.items():
                    div = section.find("div", class_=re.compile("mode-section {}.*".format(view)))
                    for stat in stats:
                        try:
                            stat_div = div.find("div", class_=re.compile(f"{stat}.*"))
                            value = stat_div.find(class_="value")
                        except AttributeError:
                            modes[mode][view][stat] = 0
                            continue
                        modes[mode][view][stat] = value.text.replace(',', '').replace(' ', '').replace('\n', '')\
                            if value else 0
            image = soup.find("img", class_="avatar")
        except AttributeError:
            message = await self.bot.say(f"""Seu perfil no dak.gg parece não estar atualizado
                                                        Acesse {url} para atualizar""")
            await asyncio.sleep(10)
            await self.bot.delete_message(message)
            return 1

        modes["updated"] = datetime.now().strftime("%d/%m/%y, %X")

        self._data[user].update({"stats": modes})
        self._data[user].update({"avatar": image["src"]})
        self._save_data()

    async def _show_stats(self, user, ctx):
        data = self._data[user.id]
        data_string = ("Rating: {rating}\n"
                       "Partidas: {games}\n"
                       "% de vitórias: {winratio}\n"
                       "Top 10: {top10s}\n"
                       "K/D: {kd}\n"
                       "Média de dano: {deals}\n"
                       "Maior n° de abates: {mostkills}\n"
                       "Headshots: {headshots}\n"
                       "Abate mais distante: {longest}\n"
                       "Média de vida: {survival}")

        for r in user.roles:
            if r.name in self._settable_roles:
                role = r

        embed = discord.Embed(title=f"Statísticas de {user.name}", description=f"Nick no PUBG: {data['account']}\n"
                                                                               f"Cargo: {role.mention}",
                              color=role.color)
        embed.set_thumbnail(url=f"{data['avatar']}")
        for view in ["TPP", "FPP"]:
            for mode in ["SOLO", "DUO", "SQUAD"]:
                stats = data["stats"][mode.lower()][view.lower()]
                if int(stats["rating"]) > 0:
                    embed.add_field(name=f"{mode} {view}", value=data_string.format(**stats), inline=True)
        embed.set_footer(text=f"Stats obtidos em dak.gg | Dados atualizados em {data['stats']['updated']}, "
                              "utilize p!update para atualizar")
        embed.set_author(name=ctx.message.author.name, icon_url=ctx.message.author.avatar_url)
        await self.bot.say(embed=embed)

    @commands.command(pass_context=True, no_pm=True)
    async def register(self, ctx, account, region=None):
        """Registers a PUBG account to Discord user"""
        region = ["na", "sa"] if region is None else [region.lower()]
        author = ctx.message.author
        message = await self.bot.say(f"`Registrando conta {account} ao usuário {author.name}`")

        await self.bot.delete_message(ctx.message)
        self._data.update({author.id: {"account": account}})
        self._save_data()

        await self._removeroles(author)
        if await self._update(author.id, region):
            return
        await self._set_roles(ctx, author)

        await self.bot.delete_message(message)

    @commands.command(pass_context=True, no_pm=True)
    async def update(self, ctx):
        """Updates stats for registered PUBG account"""
        await self.bot.delete_message(ctx.message)
        user = ctx.message.author
        await self._removeroles(user)
        if await self._update(user.id):
            return
        await self._set_roles(ctx, user)

    @commands.command(pass_context=True)
    @checks.admin()
    async def intro(self, ctx):
        """Prints the bot tutorial"""
        await self.bot.delete_message(ctx.message)
        embed = discord.Embed(title="Boas Vindas!",
                              description="Por favor registre sua conta no PUBG seguindo as instruções abaixo para"
                                          "participar de nosso ranking!",
                              color=0x000080)
        embed.add_field(name='Utilize o comando "p!register [seu nick] [server]" para receber seu cargo',
                        value='Por exemplo, se seu nick no PUBG for xXJoseGamePlaysXx e você jogar principalmente '
                              'no servidor da América do Sul escreva "p!register xXJoseGamePlaysXx sa" no chat abaixo '
                              '(sem as aspas).\n'
                              'Regiões disponíveis: sa (América do Sul), na (América do Norte), eu (Europa), as (Asia),'
                              ' krjp (Coréia), jp (Japão), oc (Oceania), sea (Sudeste da Ásia) e ru (Rússia)',
                        inline=False)
        embed.add_field(name='Utilize o comando "p!rank" para ver suas estatísticas, '
                             'e "p!update" para atualizar seu cargo',
                        value='Você também pode usar o comando "p!rank @[usuário]" para ver o rank de outro usuário no'
                              ' server.',
                        inline=False)
        await self.bot.say(embed=embed)

    @commands.command(pass_context=True, np_pm=True)
    async def rank(self, ctx, user: discord.Member=None):
        """Prints your stats"""
        if user is None:
            user = ctx.message.author
        try:
            await self._show_stats(user, ctx)
        except KeyError:
            await self.bot.say("`Esse usuário ainda não está registrado`")

    @commands.command(pass_context=True)
    @checks.admin()
    async def update_user(self, ctx, user: discord.Member=None):
        """Updates stats for registered PUBG account"""
        await self.bot.delete_message(ctx.message)
        if user is None:
            user = ctx.message.author
        await self._removeroles(user)
        if await self._update(user.id):
            return
        await self._set_roles(ctx, user)

    @commands.command(pass_context=True, no_pm=True)
    @checks.admin()
    async def create(self, ctx):
        for role in self._settable_roles:
            await self.bot.create_role(ctx.message.server, name=role)

        await self.bot.say("Done")

    @commands.command(pass_context=True, no_pm=True)
    @checks.admin()
    async def update_all(self, ctx):
        user_list = self._data.keys()
        for user in user_list:
            user = ctx.message.server.get_member(user)
            await self._removeroles(user)
            if await self._update(user.id):
                return
            await self._set_roles(ctx, user)
            await asyncio.sleep(1)


def check_files(file):
    if not os.path.exists(f"data/pubg/{file}"):
        try:
            os.mkdir("data/pubg")
        except FileExistsError:
            pass
        finally:
            dataIO.save_json(f"data/pubg/{file}", {})


def setup(bot):
    for file in ["settings.json", "data.json"]:
        check_files(file)
    n = PUBG(bot)
    bot.add_cog(n)

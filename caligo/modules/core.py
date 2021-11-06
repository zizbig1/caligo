from hashlib import md5
from typing import ClassVar, Dict

from pymongo.errors import DuplicateKeyError
from pyrogram.types import Message

from .. import command, module, util


class CoreModule(module.Module):
    name: ClassVar[str] = "Core"

    cache: Dict[int, int]
    db: util.db.AsyncCollection
    users_db: util.db.AsyncCollection

    async def on_load(self):
        self.cache = {}
        self.db = self.bot.db.get_collection("core")
        self.users_db = util.db.AsyncClient(
            self.bot.getConfig["db_uri_anjani"]
        ).get_database("AnjaniBot").get_collection("USERS")

    async def on_message(self, message: Message):
        user = message.from_user
        if not user:
            return

        data = await self.users_db.find_one({"_id": user.id})
        if not data:
            try:
                await self.users_db.insert_one(
                    {
                        "_id": user.id,
                        "username": user.username,
                        "name": user.first_name + user.last_name if user.last_name else user.first_name,
                        "hash": self.hash_id(user.id),
                    }
                )
            except DuplicateKeyError:
                pass

    def hash_id(self, id: int) -> str:
        return md5((str(id) + "dAnjani_bot").encode()).hexdigest()  # skipcq: PTC-W1003

    @command.desc("Get or change this bot prefix")
    @command.alias("setprefix", "getprefix")
    @command.usage("[new prefix?]", optional=True)
    async def cmd_prefix(self, ctx: command.Context) -> str:
        new_prefix = ctx.input

        if not new_prefix:
            return f"The prefix is `{self.bot.prefix}`"

        self.bot.prefix = new_prefix
        await self.db.find_one_and_update(
            {"_id": self.name},
            {
                "$set": {"prefix": new_prefix}
            }
        )

        return f"Prefix set to `{self.bot.prefix}`"

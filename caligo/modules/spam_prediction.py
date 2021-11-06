"""Spam Prediction"""
# Copyright (C) 2020 - 2021  UserbotIndo Team, <https://github.com/userbotindo.git>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import asyncio
import pickle
import re
from hashlib import md5, sha256
from typing import ClassVar, Optional

import numpy as np
from numpy.typing import NDArray
from pymongo.errors import DuplicateKeyError
from pyrogram.errors import FloodWait, MessageNotModified, QueryIdInvalid
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sklearn.pipeline import Pipeline

from .. import command, listener, module, util


class SpamPrediction(module.Module):
    name: ClassVar[str] = "SpamPredict"

    db: util.db.AsyncCollection
    model: Pipeline

    async def on_load(self) -> None:
        token = self.bot.getConfig.get("sp_token")
        url = self.bot.getConfig.get("sp_url")
        if not (token and url):
            self.bot.unload_plugin(self)
            return

        self.db = util.db.AsyncClient(
            self.bot.getConfig["db_uri_anjani"]
        ).get_database("AnjaniBot").get_collection("SPAM_DUMP")
        await self.__load_model(token, url)

    async def __load_model(self, token: str, url: str) -> None:
        self.log.info("Downloading spam prediction model!")
        async with self.bot.http.get(
            url,
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3.raw",
            },
        ) as res:
            if res.status == 200:
                self.model = await util.run_sync(pickle.loads, await res.read())
            else:
                self.log.warning("Failed to download prediction model!")
                self.bot.unload_plugin(self)

    @staticmethod
    def _build_hash(content: str) -> str:
        return sha256(content.strip().encode()).hexdigest()

    def _build_hex(self, id: Optional[int]) -> str:
        return md5((str(id) + "dAnjani_bot").encode()).hexdigest()  # skipcq: PTC-W1003

    @staticmethod
    def prob_to_string(value: float) -> str:
        return str(value * 10 ** 2)[0:7]

    async def _predict(self, text: str) -> NDArray[np.float64]:
        return await util.run_sync(self.model.predict_proba, [text])

    async def _is_spam(self, text: str) -> bool:
        return (await util.run_sync(self.model.predict, [text]))[0] == "spam"

    @listener.pattern(r"spam_check_(t|f)")
    async def on_callback_query(self, query: CallbackQuery) -> None:
        method = query.matches[0].group(1)
        message = query.message
        content = re.compile(r"([A-Fa-f0-9]{64})").search(message.text)
        author = query.from_user.id

        if not content:
            self.log.warning("Can't get hash from 'MessageID: %d'", message.message_id)
            return

        content_hash = content[0]

        if message.reply_markup and isinstance(message.reply_markup, InlineKeyboardMarkup):
            data = await self.db.find_one({"_id": content_hash})
            if not data:
                await query.answer("The voting poll for this message has ended!")
                return
            users_on_correct = data["spam"]
            users_on_incorrect = data["ham"]
            if method == "t":
                # Check user in incorrect data
                if author in users_on_incorrect:
                    users_on_incorrect.remove(author)
                if author in users_on_correct:
                    users_on_correct.remove(author)
                else:
                    users_on_correct.append(author)
            elif method == "f":
                # Check user in correct data
                if author in users_on_correct:
                    users_on_correct.remove(author)
                if author in users_on_incorrect:
                    users_on_incorrect.remove(author)
                else:
                    users_on_incorrect.append(author)
            else:
                raise ValueError("Unknown method")
        else:
            return

        await self.db.update_one(
            {"_id": content_hash}, {"$set": {"spam": users_on_correct, "ham": users_on_incorrect}}
        )

        total_correct, total_incorrect = len(users_on_correct), len(users_on_incorrect)
        button = [
            [
                InlineKeyboardButton(
                    text=f"✅ Correct ({total_correct})",
                    callback_data="spam_check_t",
                ),
                InlineKeyboardButton(
                    text=f"❌ Incorrect ({total_incorrect})",
                    callback_data="spam_check_f",
                ),
            ],
        ]

        if isinstance(query.message.reply_markup, InlineKeyboardMarkup):
            old_btn = query.message.reply_markup.inline_keyboard
            if len(old_btn) > 1:
                button.append(old_btn[1])

        for i in data["msg_id"]:
            try:
                while True:
                    try:
                        await self.bot.bot_client.edit_message_reply_markup(
                            -1001314588569, i, InlineKeyboardMarkup(button)
                        )
                    except MessageNotModified:
                        await query.answer(
                            "You already voted this content, "
                            "this happened because there are multiple same of contents exists.",
                            show_alert=True,
                        )
                    except FloodWait as flood:
                        await query.answer(
                            f"Please wait i'm updating the content for you.",
                            show_alert=True,
                        )
                        await asyncio.sleep(flood.x)
                        continue

                    await asyncio.sleep(0.1)
                    break
            except QueryIdInvalid:
                self.log.debug("Can't edit message, invalid query id '%s'", query.id)
                continue

        try:
            await query.answer()
        except QueryIdInvalid:
            pass

    async def on_message(self, message: Message) -> None:
        """Checker service for message"""
        chat = message.chat
        user = message.from_user
        text = (
            message.text.strip()
            if message.text
            else (message.caption.strip() if message.media and message.caption else None)
        )
        if not chat or message.left_chat_member or not user or not text:
            return

        if user.is_bot:
            return

        data = await self.db.find_one({"_id": self._build_hash(text)})
        if data is not None:
            return

        # Always check the spam probability
        await self.spam_check(message, text)
        await asyncio.sleep(1)

    async def spam_check(self, message: Message, text: str) -> None:
        user = message.from_user.id

        response = await self._predict(text.strip())
        if response.size == 0:
            return

        probability = response[0][1]
        if probability <= 0.5:
            return

        content_hash = self._build_hash(text)
        data = await self.db.find_one({"_id": content_hash})
        if data is not None:
            return

        identifier = self._build_hex(user)
        proba_str = self.prob_to_string(probability)

        notice = (
            "#SPAM_PREDICTION\n\n"
            f"**Prediction Result**: {proba_str}\n"
            f"**Identifier:** `{identifier}`\n"
        )
        if ch := message.forward_from_chat:
            notice += f"**Channel ID:** `{self._build_hex(ch.id)}`\n"
        notice += f"**Message Hash:** `{content_hash}`\n\n**====== CONTENT =======**\n\n{text}"

        data = await self.db.find_one({"_id": content_hash})
        l_spam, l_ham = 0, 0
        if data:
            l_spam = len(data["spam"])
            l_ham = len(data["ham"])

        keyb = [
            [
                InlineKeyboardButton(text=f"✅ Correct ({l_spam})", callback_data="spam_check_t"),
                InlineKeyboardButton(text=f"❌ Incorrect ({l_ham})", callback_data="spam_check_f"),
            ]
        ]

        if message.chat.username:
            keyb.append(
                [InlineKeyboardButton(text="Chat", url=f"https://t.me/{message.chat.username}")]
            )
        if message.forward_from_chat and message.forward_from_chat.username:
            raw_btn = InlineKeyboardButton(
                text="Channel", url=f"https://t.me/{message.forward_from_chat.username}"
            )
            if message.chat.username:
                keyb[1].append(raw_btn)
            else:
                keyb.append([raw_btn])

        while True:
            try:
                data = await self.db.find_one({"_id": content_hash})
                if data is not None:
                    return

                msg = await self.bot.bot_client.send_message(
                    chat_id=-1001314588569,
                    text=notice,
                    disable_web_page_preview=True,
                    reply_markup=InlineKeyboardMarkup(keyb),
                )
            except FloodWait as flood:
                if isinstance(flood.x, int):
                    await asyncio.sleep(flood.x)
                continue

            await asyncio.sleep(0.1)
            break

        if data:
            await self.db.update_one({"_id": content_hash}, {"$push": {"msg_id": msg.message_id}})
        else:
            try:
                await self.db.insert_one(
                    {
                        "_id": content_hash,
                        "text": text,
                        "spam": [],
                        "ham": [],
                        "proba": probability,
                        "msg_id": [msg.message_id],
                        "date": util.time.sec(),
                    }
                )
            except DuplicateKeyError:
                await self.db.update_one({"_id": content_hash}, {"$push": {"msg_id": msg.message_id}})

    async def cmd_update_model(self, _: command.Context) -> str:
        token = self.bot.getConfig.get("sp_token")
        url = self.bot.getConfig.get("sp_url")
        if not (token and url):
            return "No token provided!"

        await self.__load_model(token, url)
        return "Done"

import sys
from typing import TYPE_CHECKING, Any

import certifi

from .base import Base
from .. import util

if TYPE_CHECKING:
    from .bot import Bot


class DatabaseProvider(Base):
    db: util.db.AsyncDB

    def __init__(self: "Bot", **kwargs: Any) -> None:
        uri = self.getConfig["db_uri"]
        if not uri:
            raise RuntimeError("DB_URI must be set before running the bot")

        if sys.platform == "win32":
            ca = certifi.where()
            client = util.db.AsyncClient(uri, tlsCAFile=ca)
        else:
            client = util.db.AsyncClient(uri, connect=False)
        self.db = client.get_database("caligo")

        super().__init__(**kwargs)

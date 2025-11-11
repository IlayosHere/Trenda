from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class DatabaseSettings:
    dbname: str = os.getenv("DATA_RETRIEVER_DB_NAME", "trenda")
    user: str = os.getenv("DATA_RETRIEVER_DB_USER", "postgres")
    password: str = os.getenv("DATA_RETRIEVER_DB_PASSWORD", "heblish123")
    host: str = os.getenv("DATA_RETRIEVER_DB_HOST", "localhost")
    port: str = os.getenv("DATA_RETRIEVER_DB_PORT", "5432")
    options: str = os.getenv("DATA_RETRIEVER_DB_OPTIONS", "-c search_path=trenda")

    def as_dict(self) -> Dict[str, str]:
        return {
            "dbname": self.dbname,
            "user": self.user,
            "password": self.password,
            "host": self.host,
            "port": self.port,
            "options": self.options,
        }


POSTGRES_DB = DatabaseSettings().as_dict()

# app/uow.py
from __future__ import annotations
from types import TracebackType
from typing import Optional, Type
from sqlalchemy.ext.asyncio import AsyncSession

class UnitOfWork:
    def __init__(self, session: AsyncSession):
        self.session = session
        self._context_depth = 0
       
    async def __aenter__(self) -> UnitOfWork:
        self._context_depth += 1
        return self

    async def __aexit__(
        self, 
        exc_type: Optional[Type[BaseException]], 
        exc_val: Optional[BaseException], 
        exc_tb: Optional[TracebackType]
    ) -> None:
        if exc_type is not None:
            await self.rollback()
        self._context_depth -= 1
        if self._context_depth == 0:
            await self.session.close()

    async def flush(self) -> None: await self.session.flush()
    async def commit(self) -> None: await self.session.commit()
    async def rollback(self) -> None: await self.session.rollback()

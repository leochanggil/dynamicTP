from __future__ import annotations
import asyncio
import aiohttp

class TelegramNotifier:
    def __init__(self, session: aiohttp.ClientSession, enabled: bool, bot_token: str, chat_id: str):
        self.session = session
        self.enabled = enabled and bool(bot_token) and bool(chat_id)
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._q: asyncio.Queue[str] = asyncio.Queue(maxsize=200)
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if not self.enabled: return
        self._task = asyncio.create_task(self._worker())

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            try: await self._task
            except: pass

    async def send(self, text: str) -> None:
        if not self.enabled: return
        text = text[:3500]
        try: self._q.put_nowait(text)
        except asyncio.QueueFull: pass

    async def _worker(self) -> None:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        while True:
            try:
                text = await self._q.get()
                payload = {"chat_id": self.chat_id, "text": text}
                async with self.session.post(url, json=payload, timeout=5):
                    pass
                self._q.task_done()
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(1.0)
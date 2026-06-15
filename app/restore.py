from aiogram import Bot



import os
import shutil
import tempfile
import zipfile

from app.config import DB_PATH, OWNER_ID
from app.userbot import get_userbot_client


async def auto_restore_latest_backup(bot: Bot) -> bool:
    """
    Owner private chatidagi eng oxirgi Backup zipni
    yuklab olib DB_PATH ga tiklaydi.
    """

    client = await get_userbot_client()

    async for msg in client.iter_messages(OWNER_ID, limit=100):

        if not msg.document:
            continue

        caption = (msg.message or "").lower()

        filename = (getattr(msg.file, "name", "") or "").lower()

        if "backup" not in caption:
            continue

        if not filename.endswith(".zip"):
            continue

        temp_dir = tempfile.mkdtemp(prefix="restore_")

        try:
            zip_path = await msg.download_media(
                file=os.path.join(temp_dir, filename)
            )

            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(temp_dir)

            db_file = os.path.join(temp_dir, "bot.db")

            if not os.path.exists(db_file):
                continue

            os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

            shutil.copy2(db_file, DB_PATH)
          
            await bot.send_message(
              OWNER_ID,
              f"✅ Backup avtomatik tiklandi\n\n"
              f"📦 Fayl: {file_name}"
              )

            return True

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    return False

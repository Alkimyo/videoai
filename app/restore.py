import os
import shutil
import tempfile
import traceback
import zipfile

from aiogram import Bot

from app.config import (
    DB_PATH,
    OWNER_ID,
    BACKUP_CHANNEL_ID,
)
from app.userbot import get_userbot_client


async def auto_restore_latest_backup(bot: Bot) -> bool:
    try:
        await bot.send_message(
            OWNER_ID,
            "🚀 Auto restore boshlandi"
        )

        client = await get_userbot_client()

        entity = await client.get_entity(
            BACKUP_CHANNEL_ID
        )

        await bot.send_message(
            OWNER_ID,
            "✅ Backup kanali topildi"
        )

        async for msg in client.iter_messages(
            entity,
            limit=100
        ):

            if not msg.document:
                continue

            caption = (
                (msg.message or "")
                .strip()
                .lower()
            )

            filename = (
                getattr(msg.file, "name", "")
                or ""
            ).lower()

            if "backup" not in caption:
                continue

            if not filename.endswith(".zip"):
                continue

            await bot.send_message(
                OWNER_ID,
                f"📦 Backup topildi\n{filename}"
            )

            temp_dir = tempfile.mkdtemp(
                prefix="restore_"
            )

            try:
                zip_path = await msg.download_media(
                    file=os.path.join(
                        temp_dir,
                        filename
                    )
                )

                await bot.send_message(
                    OWNER_ID,
                    "✅ Zip yuklandi"
                )

                with zipfile.ZipFile(
                    zip_path,
                    "r"
                ) as z:
                    z.extractall(temp_dir)

                await bot.send_message(
                    OWNER_ID,
                    "✅ Zip ochildi"
                )

                db_file = os.path.join(
                    temp_dir,
                    "bot.db"
                )

                if not os.path.exists(db_file):

                    await bot.send_message(
                        OWNER_ID,
                        "❌ bot.db topilmadi"
                    )

                    continue

                os.makedirs(
                    os.path.dirname(DB_PATH),
                    exist_ok=True
                )

                shutil.copy2(
                    db_file,
                    DB_PATH
                )

                await bot.send_message(
                    OWNER_ID,
                    f"🎉 Backup avtomatik tiklandi\n\n"
                    f"📦 {filename}"
                )

                return True

            finally:
                shutil.rmtree(
                    temp_dir,
                    ignore_errors=True
                )

        await bot.send_message(
            OWNER_ID,
            "⚠️ Kanalda backup topilmadi"
        )

        return False

    except Exception:

        tb = traceback.format_exc()

        try:
            await bot.send_message(
                OWNER_ID,
                f"🔥 Restore xatosi\n\n{tb[:3500]}"
            )
        except Exception:
            pass

        return False

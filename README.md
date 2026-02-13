# DRAMALARUZBEKBOT (aiogram)

## Run

```bash
pip install -r requirements.txt
python -m app
```

## Admin flow

- Add mandatory channels: `/addchannel @channelname` or `/addchannel -100...`
- Private channel: `/addchannel -100... <invite_link>`
- Remove channel: `/delchannel @channelname` or `/delchannel -100...`
- Add drama: `/addserial` (inline buttons)
- Add drama part: `/addpart <drama_name|code>` then send video/document
- Send drama: `/serial <name|code>` (numeric codes or title)
- Share drama: `https://t.me/<bot_username>?start=<drama_code>`
- Admin panel: `/admin` (inline buttons)
- Stats: `/stats` (admin)
- Backup: `/backup` (admin, DB + log zip)
- Log file: `/logfile` (admin)
- Restore DB: `/restoredb` (owner, upload zip/db), cancel with `/cancelrestore`
- Post template: `/post <drama_code>` (admin, optional image)
- VIP: `/addvip <user_id>`, `/delvip <user_id>`, `/viplist`, `/setvipprice <sum>`, `/vipprice`
- VIP message: `/vipmsg` (admin)
- Broadcast: `/broadcast <text>` or reply with image/video

`SOURCE_CHANNEL_ID` must be set for drama uploads.

## Web page

Set `WEBAPP_ENABLED=1` to show a simple page at `/` with text "Ishlamoqda".

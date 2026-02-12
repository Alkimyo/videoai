# Serialbot (aiogram)

## Run

```bash
pip install -r requirements.txt
python -m app
```

## Admin flow

- Add mandatory channels: `/addchannel @channelname` or `/addchannel -100...`
- Private channel: `/addchannel -100... <invite_link>`
- Remove channel: `/delchannel @channelname` or `/delchannel -100...`
- Add serial: `/addserial` (inline buttons)
- Add serial part: `/addpart <serial_name|code>` then send video/document
- Send serial: `/serial <name|code>` (numeric codes or title)
- Share serial: `https://t.me/<bot_username>?start=<serial_code>`
- Admin panel: `/admin` (inline buttons)
- Stats: `/stats` (admin)
- Backup: `/backup` (admin, DB + log zip)
- Log file: `/logfile` (admin)
- Restore DB: `/restoredb` (owner, upload zip/db), cancel with `/cancelrestore`
- Post template: `/post <serial_code>` (admin, optional image)
- Broadcast: `/broadcast <text>` or reply with image/video

`SOURCE_CHANNEL_ID` must be set for serial uploads.

## Web page

Set `WEBAPP_ENABLED=1` to show a simple page at `/` with text "Ishlamoqda".

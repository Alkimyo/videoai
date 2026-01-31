# Kinobot (aiogram)

## Run

```bash
pip install -r requirements.txt
python -m app
```

## Admin flow

- Add mandatory channels: `/addchannel @channelname` or `/addchannel -100...`
- Private channel: `/addchannel -100... <invite_link>`
- Remove channel: `/delchannel @channelname` or `/delchannel -100...`
- Add movie: `/addmovie [code]`, then send videos; click `Yuklash` to publish
- Shortcut: send a video to the bot as admin to auto-start a new code
- Send movie: user sends `CODE` or `/movie CODE` (numeric codes)
- One code can have multiple videos; repeat `/addmovie 3` up to `MAX_MOVIES_PER_CODE` (default 10)
- Admin panel: `/admin` (inline buttons)
- Stats: `/stats`
- Broadcast: `/broadcast <text>` or reply with image/video

`SOURCE_CHANNEL_ID` must be set for movie uploads.

## Web page

Set `WEBAPP_ENABLED=1` to show a simple page at `/` with text "Ishlamoqda".

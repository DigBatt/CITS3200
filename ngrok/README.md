# ngrok tunnel

Puts the dashboard on a fixed public URL, so it can be opened from any network,
not only the laptop's Wi-Fi.

| Tunnel | URL | Local port | Serves |
|---|---|---|---|
| `nuway-dashboard` | https://nuway-dashboard.ngrok.app | 5001 | Leaflet dashboard and its API, from the Flask app |

The dashboard calls the API by relative path, so this one tunnel covers both.
The domain is reserved on the team's paid ngrok account. A free account cannot
use it.

## Setup

Once per machine.

1. Install ngrok v3 from https://ngrok.com/download (Arch: `yay -S ngrok`).
2. Add the team account's authtoken:

   ```bash
   ngrok config add-authtoken <token>
   ```

   This writes it to your own ngrok config, never to this repo.
   `ngrok config check` prints where that is: `~/.config/ngrok/ngrok.yml` on
   Linux, `~/Library/Application Support/ngrok/ngrok.yml` on macOS.

## Run it

Two terminals, from the repo root.

```bash
FLASK_APP=backend.app:create_app flask run --port 5001
```

```bash
ngrok start --all --config ~/.config/ngrok/ngrok.yml --config ngrok/ngrok.yml
```

Pass your own config first, at the path `ngrok config check` printed. Once
`--config` is given ngrok stops reading the default one, so without it there
is no authtoken.

Then open https://nuway-dashboard.ngrok.app. ngrok shows every request it
forwards at http://127.0.0.1:4040.

## Changing the URL

Reserve the domain on the account first (Domains in the ngrok dashboard).
Then change it here and restart ngrok.

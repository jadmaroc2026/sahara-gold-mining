import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl

from aiohttp import web
from config import BOT_TOKEN
from database import ensure_user, get_user

MAX_AUTH_AGE = 3600

def verify_init_data(init_data):
    if not init_data or not BOT_TOKEN:
        return None
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
        data = dict(pairs)
        if len(data) != len(pairs):
            return None
        received_hash = data.pop("hash", None)
        if not received_hash:
            return None
        auth_date = int(data.get("auth_date", "0"))
        if auth_date > int(time.time()) + 30 or int(time.time()) - auth_date > MAX_AUTH_AGE:
            return None
        check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, received_hash):
            return None
        user = json.loads(data.get("user", "{}"))
        uid = int(user["id"])
        return uid, user
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None

async def health(_request):
    return web.json_response({"ok": True, "service": "sahara-api"})

async def me(request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("tma "):
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    verified = verify_init_data(auth[4:])
    if not verified:
        return web.json_response({"ok": False, "error": "invalid_or_expired_init_data"}, status=401)
    uid, tg_user = verified
    ensure_user(uid, tg_user.get("username", ""), tg_user.get("first_name", ""))
    user = get_user(uid)
    return web.json_response({
        "ok": True,
        "user_id": uid,
        "balance": user["balance"],
        "level": user["level"],
        "frozen": bool(user["frozen"]),
        "currency": "DRJ"
    })

@web.middleware
async def cors(request, handler):
    if request.method == "OPTIONS":
        response = web.Response(status=204)
    else:
        response = await handler(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Cache-Control"] = "no-store"
    return response

async def start_api(application):
    app = web.Application(middlewares=[cors])
    app.router.add_get("/health", health)
    app.router.add_get("/api/me", me)
    app.router.add_options("/{tail:.*}", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("API_PORT", "8787"))
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    application.bot_data["api_runner"] = runner
    print(f"Sahara API listening on 127.0.0.1:{port}")

async def stop_api(application):
    runner = application.bot_data.get("api_runner")
    if runner:
        await runner.cleanup()

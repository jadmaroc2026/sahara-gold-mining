import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl

from aiohttp import web
from config import BOT_TOKEN

POSTBACK_SECRET = os.getenv('POSTBACK_SECRET', '')
MONETAG_ZONE_ID = 12166931
from database import ensure_user, get_user, claim_mining, record_monetag_event

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

async def mining_claim(request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("tma "):
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    verified = verify_init_data(auth[4:])
    if not verified:
        return web.json_response({"ok": False, "error": "invalid_or_expired_init_data"}, status=401)
    uid, _tg_user = verified
    ok, message, amount, remaining = claim_mining(uid)
    user = get_user(uid)
    return web.json_response({
        "ok": ok, "message": message, "amount": amount,
        "balance": user["balance"], "level": user["level"],
        "remaining_seconds": remaining, "currency": "DRJ"
    }, status=200 if ok else 409)


async def monetag_postback(request):
    if not POSTBACK_SECRET or not hmac.compare_digest(request.query.get("secret", ""), POSTBACK_SECRET):
        return web.Response(status=403)
    q = request.query
    try:
        uid = int(q.get("telegram_id", ""))
        zone_id = int(q.get("zone_id", "0"))
        sub_zone_raw = q.get("sub_zone_id", "")
        sub_zone_id = int(sub_zone_raw) if sub_zone_raw else None
        price = float(q.get("estimated_price", "0"))
        ymid = q.get("ymid", "")
    except (ValueError, TypeError):
        return web.Response(status=400)
    if (zone_id != MONETAG_ZONE_ID or q.get("event_type") != "impression"
            or q.get("reward_event_type") != "valued"
            or not ymid or len(ymid) > 160 or price < 0):
        return web.Response(status=200)
    record_monetag_event(uid, ymid, zone_id, sub_zone_id, price)
    return web.Response(status=200)

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
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Cache-Control"] = "no-store"
    return response

async def start_api(application):
    app = web.Application(middlewares=[cors])
    app.router.add_get("/health", health)
    app.router.add_get("/postback", monetag_postback)
    app.router.add_get("/api/me", me)
    app.router.add_post("/api/mining/claim", mining_claim)
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

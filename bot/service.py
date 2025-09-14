# bot/service.py
from __future__ import annotations
import asyncio
from typing import Any, Dict, List, Optional, Tuple

import aiohttp  # type: ignore

DEX_BASE = "https://api.dexscreener.com/latest/dex"
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=12)
_RETRIES = 2


async def _get_json(session: aiohttp.ClientSession, url: str) -> Optional[Dict[str, Any]]:
    for attempt in range(_RETRIES + 1):
        try:
            async with session.get(url, timeout=DEFAULT_TIMEOUT) as resp:
                if resp.status == 200:
                    return await resp.json()
                if resp.status in (429, 500, 502, 503, 504) and attempt < _RETRIES:
                    await asyncio.sleep(0.6 * (attempt + 1))
                    continue
                return None
        except asyncio.TimeoutError:
            if attempt < _RETRIES:
                continue
            return None
        except Exception:
            return None
    return None


def _pick_best_pair(pairs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not pairs:
        return None
    pairs.sort(
        key=lambda p: (
            (p.get("liquidity") or {}).get("usd", 0) or 0,
            (p.get("volume") or {}).get("h24", 0) or 0,
        ),
        reverse=True,
    )
    return pairs[0]


def _normalize_pair(top: Dict[str, Any]) -> Dict[str, Any]:
    base = (top.get("baseToken") or {})
    quote = (top.get("quoteToken") or {})
    price_usd = top.get("priceUsd")
    try:
        price_usd = float(price_usd) if price_usd is not None else None
    except Exception:
        price_usd = None

    mcap = top.get("marketCap")
    if mcap is None:
        mcap = top.get("fdv")
    try:
        mcap = float(mcap) if mcap is not None else None
    except Exception:
        mcap = None

    return {
        "pair_url": top.get("url"),
        "chain_id": top.get("chainId"),
        "dex_id": top.get("dexId"),
        "base_symbol": base.get("symbol"),
        "base_address": base.get("address"),
        "quote_symbol": quote.get("symbol"),
        "price_usd": price_usd,
        "market_cap": mcap,
        "fdv": top.get("fdv"),
        "liquidity_usd": (top.get("liquidity") or {}).get("usd"),
        "volume_h24": (top.get("volume") or {}).get("h24"),
    }


async def fetch_token_stats(contract: str) -> Tuple[Optional[float], Dict[str, Any]]:
    url = f"{DEX_BASE}/tokens/{contract}"
    async with aiohttp.ClientSession() as session:
        data = await _get_json(session, url)
    if not data:
        return (None, {"error": "http_or_parse_error"})

    pairs = data.get("pairs") or []
    top = _pick_best_pair(pairs)
    if not top:
        return (None, {"error": "no_pairs"})

    norm = _normalize_pair(top)
    return (norm["market_cap"], norm)


async def fetch_many_stats(contracts: List[str]) -> Dict[str, Tuple[Optional[float], Dict[str, Any]]]:
    async with aiohttp.ClientSession() as session:
        async def _one(ca: str):
            url = f"{DEX_BASE}/tokens/{ca}"
            data = await _get_json(session, url)
            if not data:
                return ca, (None, {"error": "http_or_parse_error"})
            pairs = data.get("pairs") or []
            top = _pick_best_pair(pairs)
            if not top:
                return ca, (None, {"error": "no_pairs"})
            norm = _normalize_pair(top)
            return ca, (norm["market_cap"], norm)

        results = await asyncio.gather(*(_one(ca) for ca in contracts), return_exceptions=False)
        return dict(results)

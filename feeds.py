"""Descarga y lectura de RSS/Atom sin dependencias externas."""
import email.utils
import gzip
import html.entities
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from datetime import datetime, timezone

import config
from textproc import strip_html

_XML_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}
_ENTITY_RE = re.compile(r"&([a-zA-Z][a-zA-Z0-9]*);")
_BARE_AMP_RE = re.compile(r"&(?!#?[a-zA-Z0-9]+;)")
_TRACKING = re.compile(r"^(utm_|fbclid|gclid|ns_|mc_|ref$|rss$|cmpid|int$|s_kw|ito$)", re.I)


def fetch(url, etag=None, last_modified=None, timeout=None):
    """Devuelve (status, body|None, etag, last_modified). status 304 = sin cambios."""
    headers = {
        "User-Agent": config.USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        "Accept-Encoding": "gzip, deflate",
    }
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout or config.FETCH_TIMEOUT) as r:
            body = r.read()
            enc = (r.headers.get("Content-Encoding") or "").lower() if hasattr(r, "headers") and r.headers else ""
            if enc == "gzip" or body[:2] == b"\x1f\x8b":
                body = gzip.decompress(body)
            elif enc == "deflate":
                body = zlib.decompress(body)
            h = r.headers if getattr(r, "headers", None) else {}
            return getattr(r, "status", 200) or 200, body, h.get("ETag"), h.get("Last-Modified")
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return 304, None, etag, last_modified
        raise


def _clean_xml(raw):
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    text = text.lstrip("﻿ \t\r\n")
    text = re.sub(r"^<\?xml[^>]*\?>", "", text)  # la codificación ya está resuelta

    def ent(m):
        name = m.group(1)
        if name in _XML_ENTITIES:
            return m.group(0)
        cp = html.entities.name2codepoint.get(name)
        return f"&#{cp};" if cp else f"&amp;{name};"

    text = _ENTITY_RE.sub(ent, text)
    text = _BARE_AMP_RE.sub("&amp;", text)
    return text


def _local(tag):
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def _child(el, *names):
    for c in el:
        if _local(c.tag) in names:
            return c
    return None


def _text(el, *names):
    c = _child(el, *names)
    if c is None:
        return ""
    return "".join(c.itertext()).strip()


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        dt = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        dt = None
    if dt is None:
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _image(item):
    for c in item.iter():
        tag = _local(c.tag)
        if tag in ("content", "thumbnail") and c.get("url"):
            medium = (c.get("medium") or c.get("type") or "image").lower()
            if "image" in medium or tag == "thumbnail":
                return c.get("url")
        if tag == "enclosure" and c.get("url") and "image" in (c.get("type") or "image"):
            return c.get("url")
    m = re.search(r'<img[^>]+src="([^"]+)"', _text(item, "description", "encoded", "summary") or "")
    return m.group(1) if m else None


def normalize_url(url):
    try:
        p = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return url.strip()
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True) if not _TRACKING.match(k)]
    path = p.path.rstrip("/") or "/"
    return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), path, urllib.parse.urlencode(q), ""))


def parse(raw):
    """Lista de dicts: title, url, summary, published, image."""
    root = ET.fromstring(_clean_xml(raw))
    items = [el for el in root.iter() if _local(el.tag) in ("item", "entry")]
    out = []
    for it in items:
        title = strip_html(_text(it, "title"))
        link = ""
        for c in it:
            if _local(c.tag) == "link":
                href = c.get("href")
                if href and c.get("rel", "alternate") == "alternate":
                    link = href
                    break
                if not href and (c.text or "").strip():
                    link = c.text.strip()
                    break
        if not link:
            guid = _text(it, "guid", "id")
            if guid.startswith("http"):
                link = guid
        if not title or not link:
            continue
        summary = strip_html(_text(it, "description", "summary") or _text(it, "encoded", "content"))
        published = parse_date(_text(it, "pubdate", "published", "updated", "date", "issued"))
        out.append({
            "title": title,
            "url": normalize_url(link),
            "summary": summary[:1500],
            "published": published,
            "image": _image(it),
        })
    return out


def fetch_source(src):
    """src: sqlite Row/dict de sources. Devuelve dict con resultado."""
    t0 = time.time()
    try:
        status, body, etag, lm = fetch(src["feed_url"], src["etag"], src["last_modified"])
        if status == 304:
            return {"name": src["name"], "status": "304", "items": [], "etag": etag, "last_modified": lm}
        items = parse(body)
        return {"name": src["name"], "status": "ok", "items": items, "etag": etag, "last_modified": lm,
                "elapsed": time.time() - t0}
    except Exception as e:  # un medio caído no debe parar el worker
        return {"name": src["name"], "status": f"error: {type(e).__name__}: {e}"[:300], "items": [],
                "etag": src["etag"], "last_modified": src["last_modified"]}

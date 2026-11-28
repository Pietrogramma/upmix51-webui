#!/usr/bin/env python3
"""Upmix 5.1 - interfaccia web per l'upmix stereo -> Dolby Digital 5.1 con ffmpeg.

Solo libreria standard di Python. Configurazione tramite variabili d'ambiente:
  ROOTS        cartelle esplorabili: "Nome=/percorso[:ro|:out];..."
               ":out" = cartella di uscita, ":ro" = sola lettura imposta,
               nessun suffisso = cartella della libreria, bloccata finche' non
               viene sbloccata nelle impostazioni
  PORT         porta HTTP (predefinita 8765)
  DATA         cartella per impostazioni, preset, anteprime, copertine e log (/config)
  THREADS      thread ffmpeg per le conversioni (predefinito 2)
  PASSWORD     se impostata, richiede l'accesso (utente qualsiasi, questa password)
  BACKUP_NAME  nome della cartella di backup creata nella radice scrivibile
  TMDB_API_KEY facoltativa: aggiunge le locandine di The Movie Database alla ricerca
  UA_CONTACT   facoltativo: URL o e-mail di contatto inviato a MusicBrainz nell'User-Agent

Licenza MIT - vedi il file LICENSE. Dolby e Dolby Digital sono marchi di Dolby
Laboratories; questo progetto non e' affiliato a Dolby.

Gli errori verso il browser sono codici ("error": "readonly", "params": {...})
che l'interfaccia traduce nella lingua scelta.
"""
import base64
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

VERSION = "1.4.2"
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
PORT = int(os.environ.get("PORT", "8765"))
DATA = os.environ.get("DATA", "/config")
THREADS = os.environ.get("THREADS", "2")
PASSWORD = os.environ.get("PASSWORD", "")
BACKUP_NAME = os.environ.get("BACKUP_NAME", "upmix_originali")
TMDB_KEY = os.environ.get("TMDB_API_KEY", "").strip()
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE", "ffprobe")
PREVIEW_DIR = os.path.join(DATA, "anteprime")
COVER_DIR = os.path.join(DATA, "copertine")
PRESETS_FILE = os.path.join(DATA, "preset.json")
SETTINGS_FILE = os.path.join(DATA, "impostazioni.json")
LOG_FILE = os.path.join(DATA, "upmix.log")
# MusicBrainz chiede che ogni applicazione si identifichi con nome, versione e un
# contatto (es. l'URL del progetto): https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting
CONTACT = os.environ.get("UA_CONTACT", "").strip() or "https://github.com/Pietrogramma/upmix51-webui"
UA = f"Upmix51/{VERSION} ( {CONTACT} )" if CONTACT else f"Upmix51/{VERSION} (self-hosted audio upmix tool)"
MAX_IMAGE = 20 * 1024 * 1024
UPMIX_TITLE = "Dolby Digital 5.1 (upmix)"
for d in (PREVIEW_DIR, COVER_DIR):
    os.makedirs(d, exist_ok=True)


class ApiError(Exception):
    def __init__(self, code, **params):
        super().__init__(code)
        self.code = code
        self.params = params


def fwd(p):
    """Percorsi sempre con '/' verso il browser (serve solo provando su Windows)."""
    return p.replace(os.sep, "/") if p else p


def log(msg):
    line = time.strftime("[%Y-%m-%d %H:%M:%S] ") + msg
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ================================================================ cartelle
def _parse_roots():
    """ROOTS="Nome=/percorso[:ro|:out];...".
      :out  cartella di uscita (es. CONVERTITI): sempre scrivibile, l'unica con le
            azioni rinomina/copia/sposta/cancella
      :ro   sola lettura imposta: non si puo' sbloccare dalle impostazioni
      (nulla) cartella della libreria: BLOCCATA di default, sbloccabile nelle
            impostazioni (protezione gestita dal programma)
    """
    raw = os.environ.get("ROOTS", "LIBRARY=/mnt/library;OUTPUT=/mnt/output:out")
    roots = []
    for part in raw.split(";"):
        if "=" in part:
            name, path = part.split("=", 1)
            path, kind = path.strip(), "lib"
            for flag in (":ro", ":out"):
                if path.lower().endswith(flag):
                    path, kind = path[:-len(flag)], flag[1:]
            path = os.path.realpath(path)
            if os.path.isdir(path):
                # access(2) restituisce EROFS sui montaggi :ro di Docker; nessun file viene creato
                sys_w = kind != "ro" and os.access(path, os.W_OK)
                roots.append({"name": name.strip(), "path": path, "kind": kind,
                              "sys_writable": sys_w, "writable": False})
    return roots


ROOTS = _parse_roots()


def apply_locks(settings=None):
    """Calcola quali cartelle sono scrivibili: l'uscita sempre, la libreria solo se
    sbloccata nelle impostazioni, mai quelle in sola lettura."""
    unlocked = set((settings or load_settings()).get("unlocked", []))
    for r in ROOTS:
        r["writable"] = r["sys_writable"] and (r["kind"] == "out" or (r["kind"] == "lib" and r["name"] in unlocked))


def public_root(r):
    return {"name": r["name"], "path": fwd(r["path"]), "kind": r["kind"],
            "sys_writable": r["sys_writable"], "writable": r["writable"]}

VIDEO_EXT = {"mkv", "mp4", "m4v", "mov", "avi", "ts", "m2ts", "mts", "mpg", "mpeg", "vob", "wmv", "webm"}
AUDIO_EXT = {"flac", "wav", "mp3", "m4a", "aac", "ogg", "opus", "wma", "ac3", "dts", "mka", "aiff", "aif"}
OUT_FORMATS = {
    "mkv": "matroska", "mka": "matroska", "mp4": "mp4", "m4v": "mp4", "mov": "mov",
    "avi": "avi", "ts": "mpegts", "m2ts": "mpegts", "mts": "mpegts", "mpg": "dvd",
    "mpeg": "dvd", "vob": "dvd", "ac3": "ac3",
}


def safe_path(path, must_exist=True):
    """Percorso reale, solo se si trova dentro una delle radici."""
    if not path:
        raise ApiError("path_missing")
    real = os.path.realpath(path)
    for r in ROOTS:
        if real == r["path"] or real.startswith(r["path"] + os.sep):
            if must_exist and not os.path.exists(real):
                raise ApiError("path_not_found")
            return real
    raise ApiError("path_forbidden")


def root_info(path):
    for r in sorted(ROOTS, key=lambda r: -len(r["path"])):
        if path == r["path"] or path.startswith(r["path"] + os.sep):
            return r
    return None


def assert_writable(path):
    """Ultima barriera: nessuna scrittura fuori dalle cartelle scrivibili."""
    r = root_info(os.path.realpath(path))
    if not r or not r["writable"]:
        raise ApiError("readonly")


def assert_output(path):
    """Rinomina, cancellazione e origine degli spostamenti: solo nella cartella di uscita."""
    r = root_info(os.path.realpath(path))
    if not r or r["kind"] != "out" or not r["writable"]:
        raise ApiError("not_output")


def ext_of(name):
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


# ================================================================ impostazioni
SETTINGS_DEFAULT = {"allow_overwrite": False, "unlocked": []}


def load_settings():
    s = dict(SETTINGS_DEFAULT)
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            s.update({k: v for k, v in json.load(f).items() if k in SETTINGS_DEFAULT})
    except (OSError, ValueError):
        pass
    return s


def save_settings(new):
    s = load_settings()
    if "allow_overwrite" in new:
        s["allow_overwrite"] = bool(new["allow_overwrite"])
        log(f"Impostazioni: sostituzione file {'ATTIVATA' if s['allow_overwrite'] else 'disattivata'}")
    if "unlock" in new:                     # {"unlock": "nome cartella", "value": true/false}
        name = str(new.get("unlock"))
        lib = {r["name"] for r in ROOTS if r["kind"] == "lib" and r["sys_writable"]}
        if name not in lib:
            raise ApiError("bad_dir")
        u = [x for x in s.get("unlocked", []) if x in lib and x != name]
        if new.get("value"):
            u.append(name)
        s["unlocked"] = sorted(u)
        log(f"Impostazioni: cartella {name} {'SBLOCCATA' if new.get('value') else 'bloccata'}")
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
    apply_locks(s)
    return s


# ================================================================ ffprobe
def probe(path):
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_format", "-show_streams", "-of", "json", path],
        capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise ApiError("probe_failed")
    data = json.loads(out.stdout or "{}")
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    audio, attachments = [], []
    for s in streams:
        tags = s.get("tags", {}) or {}
        if s.get("codec_type") == "audio":
            audio.append({
                "index": len(audio), "codec": s.get("codec_name"), "channels": s.get("channels"),
                "layout": s.get("channel_layout", ""), "rate": s.get("sample_rate"),
                "lang": tags.get("language", ""),
                # MKV usa "title", MP4 salva il nome della traccia in "name"
                "title": tags.get("title") or tags.get("name") or "",
            })
        elif s.get("codec_type") == "attachment":
            attachments.append({"index": len(attachments), "filename": tags.get("filename", ""),
                                "mimetype": tags.get("mimetype", "")})
    video = [s for s in streams if s.get("codec_type") == "video"
             and not (s.get("disposition", {}) or {}).get("attached_pic")]
    # copertina gia' presente: ffmpeg la presenta come flusso video "attached_pic"
    cover_stream = None
    all_v = [s for s in streams if s.get("codec_type") == "video"]
    for i, s in enumerate(all_v):
        if (s.get("disposition", {}) or {}).get("attached_pic"):
            cover_stream = {"index": i, "codec": s.get("codec_name")}
            break
    subs = [s for s in streams if s.get("codec_type") == "subtitle"]
    try:
        duration = float(fmt.get("duration") or 0)
    except ValueError:
        duration = 0.0
    tags = fmt.get("tags", {}) or {}
    return {
        "duration": duration,
        "size": int(fmt.get("size") or 0),
        "format": fmt.get("format_long_name", fmt.get("format_name", "")),
        "title": tags.get("title", "") or tags.get("TITLE", ""),
        "video": [{"codec": v.get("codec_name"), "width": v.get("width"), "height": v.get("height")} for v in video],
        "audio": audio,
        "subtitles": len(subs),
        "attachments": attachments,
        "cover_stream": cover_stream,
        "has_cover": cover_stream is not None or any(a["mimetype"].startswith("image/") for a in attachments),
    }


# ================================================================ filtro
DEFAULTS = {
    "fl": 0.0, "fr": 0.0, "fc": -1.4, "lfe": -9.1, "sl": -0.9, "sr": -0.9,
    "master": 2.0, "delay": 15, "shelf": -2.5, "lfe_cut": 120, "smooth": 0.3,
    "limiter": True, "bitrate": 640,
}
# chiavi dei preset predefiniti: i nomi li traduce l'interfaccia
PRESETS_BUILTIN = {
    "stalls": dict(DEFAULTS),
    "front": dict(DEFAULTS, sl=-5.0, sr=-5.0, shelf=-4.0, delay=20),
    "immersive": dict(DEFAULTS, sl=1.0, sr=1.0, fc=-3.0, shelf=-1.0, delay=10),
    "film": dict(DEFAULTS, fc=0.0, sl=-3.0, sr=-3.0, lfe=-6.0, lfe_cut=120, delay=12),
}


def db2lin(db):
    return 10 ** (float(db) / 20.0)


def num(p, key, lo, hi):
    try:
        v = float(p.get(key, DEFAULTS[key]))
    except (TypeError, ValueError):
        v = DEFAULTS[key]
    if math.isnan(v):
        v = DEFAULTS[key]
    return max(lo, min(hi, v))


def build_filter(p):
    fl, fr = db2lin(num(p, "fl", -60, 12)), db2lin(num(p, "fr", -60, 12))
    fc, lfe = db2lin(num(p, "fc", -60, 12)), db2lin(num(p, "lfe", -60, 12))
    sl, sr = db2lin(num(p, "sl", -60, 12)), db2lin(num(p, "sr", -60, 12))
    master = num(p, "master", -20, 20)
    delay = int(num(p, "delay", 0, 50))
    shelf = num(p, "shelf", -12, 6)
    cut = int(num(p, "lfe_cut", 60, 200))
    smooth = num(p, "smooth", 0, 1)
    f = ("aresample=48000,aformat=channel_layouts=stereo,"
         f"surround=chl_out=5.1(side):win_size=4096:smooth={smooth:.2f}:lfe=1:"
         f"lfe_low={max(20, cut - 40)}:lfe_high={cut}:lfe_mode=add:"
         f"fl_out={fl:.4f}:fr_out={fr:.4f}:fc_out={fc:.4f}:lfe_out={lfe:.4f}:"
         f"sl_out={sl:.4f}:sr_out={sr:.4f}")
    if delay > 0:
        f += f",adelay=delays=0|0|0|0|{delay}|{delay}"
    if abs(shelf) > 0.01:
        f += f",highshelf=f=5000:g={shelf:.2f}:c=SL+SR"
    f += f",lowpass=f={cut}:c=LFE"
    if abs(master) > 0.01:
        f += f",volume={master:.2f}dB"
    if p.get("limiter", True):
        f += ",alimiter=limit=0.891:attack=5:release=50:level=false"
    return f


# ================================================================ anteprima
def make_preview(src, track, params, start, length=30):
    pid = uuid.uuid4().hex[:12]
    out = os.path.join(PREVIEW_DIR, pid + ".flac")
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
           "-ss", str(max(0.0, float(start))), "-t", str(length), "-i", src,
           "-map", f"0:a:{int(track)}", "-af", build_filter(params), "-c:a", "flac", out]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise ApiError("preview_failed", detail=r.stderr.strip()[-300:])
    levels = channel_levels(out)
    _keep_latest(PREVIEW_DIR, 20)
    return {"id": pid, "url": f"/api/preview/{pid}.flac", "levels": levels}


def _keep_latest(folder, n):
    files = sorted((os.path.join(folder, x) for x in os.listdir(folder)), key=os.path.getmtime)
    for old in files[:-n]:
        try:
            os.remove(old)
        except OSError:
            pass


def channel_levels(path):
    r = subprocess.run(
        [FFMPEG, "-hide_banner", "-nostdin", "-i", path, "-af",
         "astats=measure_overall=none:measure_perchannel=RMS_level+Peak_level", "-f", "null", "-"],
        capture_output=True, text=True, timeout=300)
    rms, peak = [], []
    for line in r.stderr.splitlines():
        m = re.search(r"(RMS|Peak) level dB:\s*(-?[\d.]+|-inf)", line)
        if m:
            v = -120.0 if m.group(2) == "-inf" else float(m.group(2))
            (rms if m.group(1) == "RMS" else peak).append(round(v, 1))
    names = ["FL", "FR", "FC", "LFE", "SL", "SR"]
    return [{"ch": n, "rms": rms[i] if i < len(rms) else None, "peak": peak[i] if i < len(peak) else None}
            for i, n in enumerate(names)]


# ================================================================ fotogramma per la TV
THUMB_DIR = os.path.join(DATA, "fotogrammi")
os.makedirs(THUMB_DIR, exist_ok=True)


def thumbnail(src, at):
    """JPEG 480 px del fotogramma al secondo `at` (o della copertina, per i file
    solo audio). Messo in cache: stesso file e stesso secondo = stessa immagine."""
    st = os.stat(src)
    at = max(0, int(float(at or 0)))
    key = uuid.uuid5(uuid.NAMESPACE_URL, f"{src}|{st.st_mtime_ns}|{st.st_size}|{at}").hex[:16]
    out = os.path.join(THUMB_DIR, key + ".jpg")
    if os.path.isfile(out):
        return out
    # corregge i pixel non quadrati (DVD anamorfici) prima di ridimensionare
    vf = "scale=trunc(ih*dar/2)*2:ih,setsar=1,scale=480:-2"
    attempts = [["-ss", str(at), "-i", src, "-map", "0:V:0"],   # fotogramma del video
                ["-i", src, "-map", "0:v:0"]]                    # copertina / prima immagine
    for a in attempts:
        r = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *a,
                            "-frames:v", "1", "-vf", vf, "-q:v", "4", out], capture_output=True, timeout=60)
        if r.returncode == 0 and os.path.isfile(out) and os.path.getsize(out) > 0:
            _keep_latest(THUMB_DIR, 200)
            return out
        _rm(out)
    raise ApiError("not_found")


# ================================================================ copertine
COVER_RESULTS = {}          # id -> url completa (solo URL provenienti dalle ricerche)
COVER_LOCK = threading.Lock()


def http_json(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read(3_000_000).decode("utf-8", "replace"))


def _src_itunes(q):
    out = []
    for media, entity, kind in (("music", "album", "album"), ("movie", "movie", "movie"),
                                ("musicVideo", "musicVideo", "video")):
        try:
            d = http_json(f"https://itunes.apple.com/search?term={quote(q)}&media={media}&entity={entity}&limit=8")
        except (urllib.error.URLError, OSError, ValueError):
            continue
        for x in d.get("results", []):
            art = x.get("artworkUrl100") or ""
            if not art:
                continue
            out.append({
                "source": "iTunes", "kind": kind,
                "title": x.get("collectionName") or x.get("trackName") or "",
                "artist": x.get("artistName", ""),
                "year": (x.get("releaseDate") or "")[:4],
                "thumb": art.replace("100x100bb", "300x300bb"),
                "full": art.replace("100x100bb", "1200x1200bb"),
                "size": "1200×1200",
            })
    return out


def _src_deezer(q):
    try:
        d = http_json(f"https://api.deezer.com/search/album?q={quote(q)}&limit=10")
    except (urllib.error.URLError, OSError, ValueError):
        return []
    out = []
    for x in d.get("data", []):
        if x.get("cover_xl"):
            out.append({"source": "Deezer", "kind": "album", "title": x.get("title", ""),
                        "artist": (x.get("artist") or {}).get("name", ""), "year": "",
                        "thumb": x.get("cover_medium") or x.get("cover_xl"),
                        "full": x["cover_xl"], "size": "1000×1000"})
    return out


def _src_musicbrainz(q):
    try:
        d = http_json(f"https://musicbrainz.org/ws/2/release-group/?query={quote(q)}&fmt=json&limit=8")
    except (urllib.error.URLError, OSError, ValueError):
        return []
    out = []
    for x in d.get("release-groups", []):
        rid = x.get("id")
        if not rid:
            continue
        credit = x.get("artist-credit") or []
        out.append({"source": "MusicBrainz", "kind": (x.get("primary-type") or "album").lower(),
                    "title": x.get("title", ""),
                    "artist": credit[0].get("name", "") if credit else "",
                    "year": (x.get("first-release-date") or "")[:4],
                    "thumb": f"https://coverartarchive.org/release-group/{rid}/front-250",
                    "full": f"https://coverartarchive.org/release-group/{rid}/front", "size": ""})
    return out


def _src_tmdb(q):
    if not TMDB_KEY:
        return []
    try:
        d = http_json(f"https://api.themoviedb.org/3/search/multi?api_key={quote(TMDB_KEY)}&query={quote(q)}")
    except (urllib.error.URLError, OSError, ValueError):
        return []
    out = []
    for x in d.get("results", [])[:10]:
        p = x.get("poster_path")
        if p:
            out.append({"source": "TMDb", "kind": "movie", "title": x.get("title") or x.get("name") or "",
                        "artist": "", "year": (x.get("release_date") or x.get("first_air_date") or "")[:4],
                        "thumb": f"https://image.tmdb.org/t/p/w342{p}",
                        "full": f"https://image.tmdb.org/t/p/original{p}", "size": ""})
    return out


def cover_search(q):
    q = re.sub(r"\s+", " ", q).strip()[:120]
    if len(q) < 2:
        raise ApiError("cover_query")
    sources = (_src_itunes, _src_deezer, _src_musicbrainz, _src_tmdb)
    with ThreadPoolExecutor(4) as ex:
        parts = list(ex.map(lambda f: f(q), sources))
    # titolo molto specifico e pochi risultati: riprova con le prime parole (di solito l'artista)
    words = q.split()
    if sum(len(p) for p in parts) < 12 and len(words) > 3:
        q2 = " ".join(words[:3])
        with ThreadPoolExecutor(4) as ex:
            extra = list(ex.map(lambda f: f(q2), sources))
        parts = [a + b for a, b in zip(parts, extra)]
    results, seen = [], set()
    # alterna le fonti, cosi' i primi risultati vengono da fonti diverse
    for i in range(max((len(p) for p in parts), default=0)):
        for p in parts:
            if i < len(p) and p[i]["full"] not in seen:
                seen.add(p[i]["full"])
                rid = uuid.uuid4().hex[:12]
                with COVER_LOCK:
                    COVER_RESULTS[rid] = p[i]["full"]
                item = dict(p[i], id=rid)
                item.pop("full")
                results.append(item)
    with COVER_LOCK:  # limita la memoria
        while len(COVER_RESULTS) > 2000:
            COVER_RESULTS.pop(next(iter(COVER_RESULTS)))
    return results


def _image_kind(head):
    if head[:3] == b"\xff\xd8\xff":
        return "jpg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return None


def store_cover(data):
    """Salva un'immagine come JPEG in COVER_DIR e restituisce le sue informazioni."""
    kind = _image_kind(data[:16])
    if not kind:
        raise ApiError("cover_not_image")
    cid = uuid.uuid4().hex[:12]
    dst = os.path.join(COVER_DIR, cid + ".jpg")
    if kind == "jpg":
        with open(dst, "wb") as f:
            f.write(data)
    else:
        tmp = os.path.join(COVER_DIR, cid + ".src")
        with open(tmp, "wb") as f:
            f.write(data)
        r = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", tmp,
                            "-frames:v", "1", "-q:v", "2", dst], capture_output=True, timeout=60)
        os.remove(tmp)
        if r.returncode != 0:
            raise ApiError("cover_not_image")
    w = h = 0
    pr = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
                         "stream=width,height", "-of", "csv=p=0", dst], capture_output=True, text=True, timeout=30)
    try:
        w, h = (int(x) for x in pr.stdout.strip().split(",")[:2])
    except ValueError:
        pass
    _keep_latest(COVER_DIR, 50)
    return {"cover_id": cid, "url": f"/api/cover/img/{cid}.jpg", "width": w, "height": h}


def cover_fetch(rid):
    with COVER_LOCK:
        url = COVER_RESULTS.get(rid)
    if not url:
        raise ApiError("cover_not_found")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read(MAX_IMAGE + 1)
    except (urllib.error.URLError, OSError):
        raise ApiError("cover_download")
    if len(data) > MAX_IMAGE:
        raise ApiError("cover_too_big")
    return store_cover(data)


def cover_path(cid):
    if not cid:
        return None
    if not re.fullmatch(r"[0-9a-f]{12}", str(cid)):
        raise ApiError("cover_not_found")
    p = os.path.join(COVER_DIR, cid + ".jpg")
    if not os.path.isfile(p):
        raise ApiError("cover_not_found")
    return p


# ================================================================ lavori
JOBS = {}
JOB_ORDER = []
JOB_LOCK = threading.Lock()
JOB_EVENT = threading.Event()


def new_job(spec):
    jid = uuid.uuid4().hex[:10]
    job = dict(spec, id=jid, state="queued", progress=0.0, msgs=[], error=None, created=time.time(), proc=None)
    with JOB_LOCK:
        JOBS[jid] = job
        JOB_ORDER.append(jid)
    JOB_EVENT.set()
    return job


def public_job(j):
    out = {k: v for k, v in j.items() if k not in ("proc", "params", "info", "cover")}
    for k in ("src", "dst", "backup_path"):
        if out.get(k):
            out[k] = fwd(out[k])
    return out


def worker():
    while True:
        JOB_EVENT.wait()
        with JOB_LOCK:
            pending = [JOBS[i] for i in JOB_ORDER if JOBS[i]["state"] == "queued"]
            if not pending:
                JOB_EVENT.clear()
                continue
            job = pending[0]
            job["state"] = "running"
        try:
            # una sola operazione pesante alla volta: conversioni, copie e spostamenti
            if job.get("kind") in ("copy", "move"):
                _copy_worker(job, job["kind"] == "move")
            else:
                run_job(job)
        except ApiError as e:
            job["state"], job["error"] = "error", {"code": e.code, "params": e.params}
            log(f"ERRORE {job['src']}: {e.code} {e.params}")
        except Exception as e:  # noqa: BLE001
            job["state"], job["error"] = "error", {"code": "internal", "params": {"detail": str(e)}}
            log(f"ERRORE {job['src']}: {e}")


def ffmpeg_cmd(job, dst, fmt, sub_mode):
    src, track, info = job["src"], int(job["track"]), job["info"]
    has_video = bool(info["video"])
    cover = job.get("cover")
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
           "-threads", str(THREADS), "-progress", "pipe:1", "-nostats", "-i", src]
    cover_as_stream = cover and fmt in ("mp4", "mov")
    if cover_as_stream:
        cmd += ["-i", cover]
    if has_video and fmt != "ac3":
        cmd += ["-map", "0:V?"]
    cmd += ["-map", f"0:a:{track}"]
    if fmt != "ac3":
        # tracce originali da conservare: mai le vecchie tracce upmix di questo programma
        for a in info["audio"]:
            if a["title"] == UPMIX_TITLE:
                continue
            if a["index"] == track and not job.get("keep_original", True):
                continue
            cmd += ["-map", f"0:a:{a['index']}"]
        if sub_mode != "none" and has_video:
            cmd += ["-map", "0:s?"]
        n_att = 0
        if fmt == "matroska":
            if cover:
                # tiene gli allegati (es. font dei sottotitoli) ma non le vecchie copertine
                for a in info["attachments"]:
                    old_cover = a["mimetype"].startswith("image/") and re.match(
                        r"(small_)?cover", a["filename"], re.I)
                    if not old_cover:
                        cmd += ["-map", f"0:t:{a['index']}"]
                        n_att += 1
            else:
                cmd += ["-map", "0:t?"]
        if cover_as_stream:
            cmd += ["-map", "1:v:0"]
        cmd += ["-map_chapters", "0", "-map_metadata", "0", "-c", "copy"]
        if sub_mode == "srt":
            cmd += ["-c:s", "srt"]
        if cover and fmt == "matroska":
            cmd += ["-attach", cover, f"-metadata:s:t:{n_att}", "mimetype=image/jpeg",
                    f"-metadata:s:t:{n_att}", "filename=cover.jpg"]
        if cover_as_stream:
            vi = len(info["video"])
            cmd += [f"-c:v:{vi}", "mjpeg", f"-disposition:v:{vi}", "attached_pic"]
        if fmt in ("mp4", "mov"):
            cmd += ["-movflags", "+faststart"]
    cmd += ["-filter:a:0", build_filter(job["params"]), "-c:a:0", "ac3",
            "-b:a:0", f"{int(num(job['params'], 'bitrate', 192, 640))}k"]
    if fmt != "ac3":
        cmd += ["-metadata:s:a:0", "title=" + UPMIX_TITLE,
                "-disposition:a", "0", "-disposition:a:0", "default"]
    cmd += ["-f", fmt, dst]
    return cmd


def run_ffmpeg(job, cmd):
    duration = job["info"]["duration"] or 0
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    job["proc"] = proc
    err_lines = []

    def read_err():
        for line in proc.stderr:
            err_lines.append(line.strip())
    t = threading.Thread(target=read_err, daemon=True)
    t.start()
    for line in proc.stdout:
        if line.startswith(("out_time_us=", "out_time_ms=")):
            try:
                us = int(line.split("=", 1)[1])
                if duration > 0:
                    job["progress"] = max(job["progress"], min(99.0, us / 1e6 / duration * 100))
            except ValueError:
                pass
        elif line.startswith("speed="):
            job["speed"] = line.split("=", 1)[1].strip()
    proc.wait()
    t.join(timeout=2)
    job["proc"] = None
    return proc.returncode, "\n".join(err_lines[-10:])


def verify(job, path):
    try:
        info = probe(path)
    except ApiError:
        return "unreadable"
    if not info["audio"] or info["audio"][0]["channels"] != 6:
        return "no_51"
    if job["info"]["video"] and not info["video"] and job["fmt"] != "ac3":
        return "no_video"
    d0, d1 = job["info"]["duration"], info["duration"]
    if d0 and d1 and abs(d0 - d1) > max(1.0, d0 * 0.002):
        return "duration"
    return None


def run_job(job):
    src, dst, fmt = job["src"], job["dst"], job["fmt"]
    tmp = dst + ".upmixtmp"
    assert_writable(dst)
    log(f"Avvio: {src} -> {dst}")
    if job.get("cover") and fmt not in ("matroska", "mp4", "mov"):
        job["msgs"].append("cover_skipped")
        job["cover"] = None
    # nessuna copertina nuova: conserva quella gia' presente nel file
    kept = None
    cs = job["info"].get("cover_stream")
    if not job.get("cover") and cs and fmt in ("matroska", "mp4", "mov"):
        kept = os.path.join(COVER_DIR, f"keep_{job['id']}.jpg")
        enc = ["-c:v", "copy"] if cs["codec"] == "mjpeg" else ["-q:v", "2"]
        r = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", src,
                            "-map", f"0:v:{cs['index']}", "-frames:v", "1", *enc, "-f", "image2", kept],
                           capture_output=True, timeout=60)
        if r.returncode == 0 and os.path.getsize(kept) > 0:
            job["cover"] = kept
        else:
            _rm(kept)
            kept = None
    try:
        _run_and_replace(job, src, dst, fmt, tmp)
    finally:
        if kept:
            _rm(kept)


def _run_and_replace(job, src, dst, fmt, tmp):
    attempts = ["copy", "srt", "none"] if fmt == "matroska" else ["copy", "none"]
    rc, err = 1, ""
    for sub_mode in attempts:
        if job.get("cancel"):
            break
        rc, err = run_ffmpeg(job, ffmpeg_cmd(job, tmp, fmt, sub_mode))
        if rc == 0:
            if sub_mode == "srt":
                job["msgs"].append("subs_srt")
            elif sub_mode == "none" and job["info"]["subtitles"]:
                job["msgs"].append("subs_dropped")
            break
    if job.get("cancel"):
        _rm(tmp)
        job["state"] = "cancelled"
        log(f"Annullato: {src}")
        return
    if rc != 0:
        _rm(tmp)
        raise ApiError("ffmpeg", detail=(err or "?")[-400:])
    problem = verify(job, tmp)
    if problem:
        _rm(tmp)
        raise ApiError("verify", reason=problem)
    try:  # stessi proprietario e permessi dell'originale
        st = os.stat(src)
        os.chmod(tmp, st.st_mode & 0o7777)
        if hasattr(os, "chown"):
            os.chown(tmp, st.st_uid, st.st_gid)
    except OSError:
        pass
    if os.path.exists(dst):
        # sovrascrittura: ricontrolla che sia ancora consentita
        if not (load_settings()["allow_overwrite"] and job.get("overwrite")):
            _rm(tmp)
            raise ApiError("overwrite_disabled")
        if job.get("backup", True):
            bk = backup_path(dst)
            shutil.move(dst, bk)
            job["backup_path"] = bk
    os.replace(tmp, dst)
    job["progress"] = 100.0
    job["state"] = "done"
    log(f"Completato: {dst}" + (f" (originale in {job['backup_path']})" if job.get("backup_path") else ""))


def _rm(p):
    try:
        os.remove(p)
    except OSError:
        pass


def backup_path(dst):
    """Dove salvare un file prima di sostituirlo: nella cartella di uscita
    (<uscita>/upmix_originali/<cartella>/<percorso>), cosi' i server multimediali
    non vedono doppioni nella libreria. Senza cartella di uscita: nella radice."""
    dst = os.path.realpath(dst)
    r = root_info(dst)
    outs = [x for x in ROOTS if x["kind"] == "out" and x["writable"]]
    base = os.path.join(outs[0]["path"], BACKUP_NAME, r["name"]) if outs else os.path.join(r["path"], BACKUP_NAME)
    bk = os.path.join(base, os.path.relpath(dst, r["path"]))
    if os.path.exists(bk):
        stem, ext = os.path.splitext(bk)
        bk = f"{stem}.{time.strftime('%Y%m%d-%H%M%S')}{ext}"
    os.makedirs(os.path.dirname(bk), exist_ok=True)
    return bk


# ================================================================ operazioni sui file
# Rinomina, cancellazione e origine degli spostamenti: solo nella cartella di uscita.
# Copia e spostamento possono sostituire un file esistente solo con l'impostazione
# attiva e la conferma dell'utente; il file sostituito va sempre nel backup.
# I file usati da un lavoro in corso sono bloccati.

def _valid_name(name):
    name = (name or "").strip()
    if not name or name in (".", "..") or "/" in name or "\\" in name or name.startswith(".") \
            or name.endswith(".upmixtmp") or len(name) > 255 or any(ord(c) < 32 for c in name):
        raise ApiError("bad_name")
    return name


def _file_in_use(*paths):
    with JOB_LOCK:
        for j in JOBS.values():
            if j["state"] in ("queued", "running"):
                for p in paths:
                    if p in (j.get("src"), j.get("dst")):
                        return True
    return False


def _source_file(path, need_output):
    src = safe_path(path)
    if not os.path.isfile(src):
        raise ApiError("not_file")
    if need_output:
        assert_output(src)
    if _file_in_use(src):
        raise ApiError("busy")
    return src


def _target(destdir, name, overwrite=False):
    d = safe_path(destdir)
    if not os.path.isdir(d):
        raise ApiError("bad_dir")
    assert_writable(d)
    dst = safe_path(os.path.join(d, _valid_name(name)), must_exist=False)
    if os.path.exists(dst):
        if not os.path.isfile(dst):
            raise ApiError("bad_name")
        if not load_settings()["allow_overwrite"]:
            raise ApiError("dest_exists", can_overwrite=False)
        if not overwrite:                   # serve la conferma esplicita dell'utente
            raise ApiError("dest_exists", can_overwrite=True)
    if _file_in_use(dst):
        raise ApiError("busy")
    return dst


def file_rename(path, newname):
    src = _source_file(path, True)
    dst = _target(os.path.dirname(src), newname)
    os.rename(src, dst)
    log(f"Rinominato: {src} -> {os.path.basename(dst)}")
    return {"ok": True, "path": fwd(dst)}


def file_delete(path):
    src = _source_file(path, True)
    os.remove(src)
    log(f"Cancellato: {src}")
    return {"ok": True}


def file_copy_move(path, destdir, newname, move, overwrite=False):
    src = _source_file(path, move)          # la copia puo' partire da qualsiasi cartella (sola lettura)
    dst = _target(destdir, newname or os.path.basename(src), overwrite)
    if os.path.realpath(dst) == os.path.realpath(src):
        raise ApiError("dest_exists", can_overwrite=False)
    replace = os.path.exists(dst)
    if move and not replace:
        try:                                # stesso disco: istantaneo
            os.rename(src, dst)
            log(f"Spostato: {src} -> {dst}")
            return {"ok": True, "instant": True, "path": fwd(dst)}
        except OSError:
            pass                            # dischi diversi: copia e poi cancella
    jid = uuid.uuid4().hex[:10]
    job = {"id": jid, "kind": "move" if move else "copy", "state": "queued", "progress": 0.0,
           "msgs": [], "error": None, "created": time.time(), "proc": None,
           "src": src, "dst": dst, "name": os.path.basename(src), "outname": os.path.basename(dst),
           "replace": replace}
    with JOB_LOCK:
        JOBS[jid] = job
        JOB_ORDER.append(jid)
    JOB_EVENT.set()                         # entra nella coda unica (vedi worker)
    return {"ok": True, "job": public_job(job)}


def _copy_worker(job, move):
    src, dst = job["src"], job["dst"]
    tmp = dst + ".upmixtmp"
    same_disk = move and os.stat(src).st_dev == os.stat(os.path.dirname(dst)).st_dev
    try:
        if not same_disk:
            _copy_to_tmp(job, src, tmp)
        if os.path.exists(dst):
            # sostituzione: ricontrolla l'impostazione e salva il file esistente
            if not (job.get("replace") and load_settings()["allow_overwrite"]):
                raise ApiError("dest_exists", can_overwrite=False)
            bk = backup_path(dst)
            shutil.move(dst, bk)
            job["backup_path"] = bk
        if same_disk:
            os.rename(src, dst)
        else:
            os.replace(tmp, dst)
            if move:
                os.remove(src)
        job["progress"], job["state"] = 100.0, "done"
        log(f"{'Spostato' if move else 'Copiato'}: {src} -> {dst}"
            + (f" (precedente in {job['backup_path']})" if job.get("backup_path") else ""))
    except InterruptedError:
        _rm(tmp)
        job["state"] = "cancelled"
    except ApiError as e:
        _rm(tmp)
        job["state"], job["error"] = "error", {"code": e.code, "params": e.params}
    except OSError as e:
        _rm(tmp)
        job["state"], job["error"] = "error", {"code": "internal", "params": {"detail": str(e)}}


def _copy_to_tmp(job, src, tmp):
    total = os.path.getsize(src) or 1
    done = 0
    with open(src, "rb") as fi, open(tmp, "wb") as fo:
        while True:
            if job.get("cancel"):
                raise InterruptedError
            chunk = fi.read(8 * 1024 * 1024)
            if not chunk:
                break
            fo.write(chunk)
            done += len(chunk)
            job["progress"] = min(99.0, done / total * 100)
    if os.path.getsize(tmp) != os.path.getsize(src):
        raise ApiError("verify", reason="size")
    shutil.copystat(src, tmp)
    try:
        st = os.stat(src)
        if hasattr(os, "chown"):
            os.chown(tmp, st.st_uid, st.st_gid)
    except OSError:
        pass


# ================================================================ preset
def load_presets():
    user = {}
    try:
        with open(PRESETS_FILE, encoding="utf-8") as f:
            user = json.load(f)
    except (OSError, ValueError):
        pass
    return {"builtin": PRESETS_BUILTIN, "user": user, "defaults": DEFAULTS}


def save_preset(name, params):
    data = load_presets()["user"]
    if params is None:
        data.pop(name, None)
    else:
        data[name] = {k: params.get(k, DEFAULTS[k]) for k in DEFAULTS}
    with open(PRESETS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ================================================================ HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = f"Upmix51/{VERSION}"

    def log_message(self, fmt, *args):
        pass

    def _auth(self):
        if not PASSWORD:
            return True
        h = self.headers.get("Authorization", "")
        if h.startswith("Basic "):
            try:
                _, pw = base64.b64decode(h[6:]).decode("utf-8").split(":", 1)
                if pw == PASSWORD:
                    return True
            except (ValueError, UnicodeDecodeError):
                pass
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="Upmix 5.1"')
        self.end_headers()
        return False

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _err(self, code, params=None, status=400):
        self._json({"error": code, "params": params or {}}, status)

    def _file(self, path, ctype):
        try:
            size = os.path.getsize(path)
        except OSError:
            return self._err("not_found", status=404)
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            start = int(a) if a else 0
            end = int(b) if b else size - 1
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = f.read(min(65536, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                remaining -= len(chunk)

    def _raw(self, limit):
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ApiError("cover_too_big")
        return self.rfile.read(n) if n else b""

    def _body(self):
        raw = self._raw(1_000_000)
        return json.loads(raw or b"{}")

    # ---------------- GET
    def do_GET(self):
        if not self._auth():
            return
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path in ("/", "/index.html"):
                return self._file(os.path.join(STATIC, "index.html"), "text/html; charset=utf-8")
            if u.path == "/api/roots":
                return self._json([public_root(r) for r in ROOTS])
            if u.path == "/api/list":
                return self._json(self.list_dir(q.get("path", ""), q.get("dirs") == "1"))
            if u.path == "/api/info":
                return self._json(probe(safe_path(q.get("path"))))
            if u.path.startswith("/api/preview/"):
                name = os.path.basename(u.path)
                if not re.fullmatch(r"[0-9a-f]{12}\.flac", name):
                    return self._err("not_found", status=404)
                return self._file(os.path.join(PREVIEW_DIR, name), "audio/flac")
            if u.path.startswith("/api/cover/img/"):
                name = os.path.basename(u.path)
                if not re.fullmatch(r"[0-9a-f]{12}\.jpg", name):
                    return self._err("not_found", status=404)
                return self._file(os.path.join(COVER_DIR, name), "image/jpeg")
            if u.path == "/api/thumb":
                return self._file(thumbnail(safe_path(q.get("path")), q.get("t", 0)), "image/jpeg")
            if u.path == "/api/cover/search":
                return self._json(cover_search(q.get("q", "")))
            if u.path == "/api/jobs":
                with JOB_LOCK:
                    return self._json([public_job(JOBS[i]) for i in reversed(JOB_ORDER)])
            if u.path == "/api/presets":
                return self._json(load_presets())
            if u.path == "/api/settings":
                return self._json(dict(load_settings(), version=VERSION, tmdb=bool(TMDB_KEY)))
            return self._err("not_found", status=404)
        except ApiError as e:
            return self._err(e.code, e.params)

    def list_dir(self, path, dirs_only):
        if not path:
            return {"path": "", "parent": None, "writable": False,
                    "entries": [dict(public_root(r), type="dir")
                                for r in ROOTS if r["writable"] or not dirs_only]}
        p = safe_path(path)
        if dirs_only and not root_info(p)["writable"]:
            raise ApiError("readonly")
        entries = []
        with os.scandir(p) as it:
            for e in it:
                if e.name.startswith(".") or e.name.endswith(".upmixtmp"):
                    continue
                try:
                    if e.is_dir():
                        entries.append({"name": e.name, "path": fwd(e.path), "type": "dir"})
                    elif not dirs_only:
                        x = ext_of(e.name)
                        if x in VIDEO_EXT or x in AUDIO_EXT:
                            entries.append({"name": e.name, "path": fwd(e.path),
                                            "type": "video" if x in VIDEO_EXT else "audio",
                                            "size": e.stat().st_size})
                except OSError:
                    continue
        entries.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))
        parent = "" if any(p == r["path"] for r in ROOTS) else fwd(os.path.dirname(p))
        ri = root_info(p)
        return {"path": fwd(p), "parent": parent, "entries": entries, "writable": ri["writable"],
                "output": ri["kind"] == "out" and ri["writable"]}

    # ---------------- POST
    def do_POST(self):
        if not self._auth():
            return
        u = urlparse(self.path)
        try:
            if u.path == "/api/cover/upload":
                return self._json(store_cover(self._raw(MAX_IMAGE)))
            b = self._body()
            if u.path == "/api/preview":
                return self._json(make_preview(safe_path(b.get("path")), b.get("track", 0),
                                               b.get("params", {}), b.get("start", 0)))
            if u.path == "/api/cover/select":
                return self._json(cover_fetch(b.get("id", "")))
            if u.path == "/api/jobs":
                return self._json(public_job(self.create_job(b)))
            if u.path == "/api/file/rename":
                return self._json(file_rename(b.get("path"), b.get("name")))
            if u.path == "/api/file/delete":
                return self._json(file_delete(b.get("path")))
            if u.path in ("/api/file/copy", "/api/file/move"):
                return self._json(file_copy_move(b.get("path"), b.get("destdir"), b.get("name"),
                                                 u.path.endswith("move"), bool(b.get("overwrite"))))
            m = re.fullmatch(r"/api/jobs/([0-9a-f]+)/(cancel|remove)", u.path)
            if m:
                with JOB_LOCK:
                    job = JOBS.get(m.group(1))
                    if not job:
                        return self._err("job_not_found", status=404)
                    if m.group(2) == "cancel":
                        job["cancel"] = True
                        if job["state"] == "queued":
                            job["state"] = "cancelled"
                        elif job.get("proc"):
                            job["proc"].terminate()
                    elif job["state"] != "running":
                        JOBS.pop(job["id"], None)
                        JOB_ORDER.remove(job["id"])
                return self._json({"ok": True})
            if u.path == "/api/presets":
                name = (b.get("name") or "").strip()[:60]
                if not name:
                    raise ApiError("preset_name")
                save_preset(name, b.get("params"))
                return self._json(load_presets())
            if u.path == "/api/settings":
                return self._json(dict(save_settings(b), version=VERSION, tmdb=bool(TMDB_KEY)))
            return self._err("not_found", status=404)
        except ApiError as e:
            return self._err(e.code, e.params)
        except ValueError:
            return self._err("bad_request")

    def create_job(self, b):
        src = safe_path(b.get("path"))
        info = probe(src)
        track = int(b.get("track", 0))
        if track < 0 or track >= len(info["audio"]):
            raise ApiError("bad_track")
        if info["audio"][track]["channels"] != 2:
            raise ApiError("not_stereo")
        outdir = safe_path(b.get("outdir"))
        if not os.path.isdir(outdir):
            raise ApiError("bad_dir")
        assert_writable(outdir)
        name = (b.get("outname") or "").strip()
        if not name or "/" in name or "\\" in name or name.startswith("."):
            raise ApiError("bad_name")
        x = ext_of(name)
        if x not in OUT_FORMATS:
            raise ApiError("bad_ext", exts=", ".join(sorted(OUT_FORMATS)))
        fmt = OUT_FORMATS[x]
        if not info["video"] and fmt not in ("matroska", "ac3"):
            raise ApiError("audio_only_ext")
        dst = safe_path(os.path.join(outdir, name), must_exist=False)
        exists = os.path.exists(dst)
        if exists:
            if not load_settings()["allow_overwrite"]:
                raise ApiError("overwrite_disabled")
            if not b.get("overwrite"):
                raise ApiError("dest_exists")
        cover = cover_path(b.get("cover_id"))
        with JOB_LOCK:
            for j in JOBS.values():
                if j["dst"] == dst and j["state"] in ("queued", "running"):
                    raise ApiError("job_running")
        spec = {
            "src": src, "dst": dst, "fmt": fmt, "track": track, "info": info,
            "params": b.get("params", {}), "replace": os.path.realpath(dst) == os.path.realpath(src),
            "overwrite": bool(exists and b.get("overwrite")), "backup": bool(b.get("backup", True)),
            "keep_original": bool(b.get("keep_original", True)), "cover": cover,
            "has_cover": bool(cover), "name": os.path.basename(src), "outname": name,
        }
        return new_job(spec)


def main():
    if not ROOTS:
        raise SystemExit("Nessuna cartella valida in ROOTS")
    apply_locks()
    threading.Thread(target=worker, daemon=True).start()
    log(f"Upmix 5.1 v{VERSION} in ascolto sulla porta {PORT} - cartelle: "
        + ", ".join(f"{r['name']}={r['path']} [{r['kind']}{', scrivibile' if r['writable'] else ', bloccata'}]" for r in ROOTS))
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()

"""Remove time spans from an audio file without re-encoding.

The kept ranges are stitched with ffmpeg's concat demuxer and stream copy, so
there is no generation loss and it runs at disk speed. Tags and cover art are
copied from the source, and chapters are shifted to match the new timeline.

The result overwrites the source *in place* (same inode). Audiobookshelf
tracks files by inode, and replacing the file with a rename would look like a
delete plus a new file to it.
"""

import os
import shutil
import subprocess
import tempfile

from . import fingerprint

# extension -> ffmpeg muxer
MUXERS = {
    ".mp3": "mp3",
    ".m4a": "mp4",
    ".m4b": "mp4",
    ".mp4": "mp4",
    ".aac": "adts",
    ".flac": "flac",
    ".ogg": "ogg",
    ".opus": "ogg",
}

AUDIO_EXTS = set(MUXERS) | {".wav", ".wma", ".webm"}


class CutError(RuntimeError):
    pass


def can_cut(path):
    return os.path.splitext(path)[1].lower() in MUXERS


def normalize_spans(spans, duration, min_len=0.5):
    """Clamp, sort, and merge removal spans; drop slivers."""
    clean = []
    for s, e in spans:
        s, e = max(0.0, float(s)), min(float(duration), float(e))
        if e - s >= min_len:
            clean.append((s, e))
    clean.sort()
    merged = []
    for s, e in clean:
        if merged and s <= merged[-1][1] + 0.25:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def keep_spans(duration, removed):
    keep, cur = [], 0.0
    for s, e in removed:
        if s > cur:
            keep.append((cur, s))
        cur = max(cur, e)
    if cur < duration:
        keep.append((cur, duration))
    return [(s, e) for s, e in keep if e - s > 0.05]


def remap(t, removed):
    """Map a time on the old timeline to the new one."""
    shift = 0.0
    for s, e in removed:
        if t >= e:
            shift += e - s
        elif t > s:
            return s - shift
        else:
            break
    return t - shift


def _ffmeta_escape(text):
    out = str(text)
    for ch in ("\\", "=", ";", "#", "\n"):
        out = out.replace(ch, "\\" + ch)
    return out


def _chapters_ffmetadata(chapters, removed, new_duration):
    lines = [";FFMETADATA1"]
    count = 0
    for ch in chapters:
        try:
            s = remap(float(ch["start_time"]), removed)
            e = remap(float(ch["end_time"]), removed)
        except (KeyError, ValueError, TypeError):
            continue
        e = min(e, new_duration)
        if e - s < 1.0:
            continue
        title = (ch.get("tags") or {}).get("title", "")
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(s * 1000)}", f"END={int(e * 1000)}",
                  f"title={_ffmeta_escape(title)}"]
        count += 1
    return "\n".join(lines) + "\n", count


def _concat_escape(path):
    return "'" + str(path).replace("'", "'\\''") + "'"


def _run(cmd, nice, timeout=3600):
    proc = subprocess.run(fingerprint.nice_prefix(nice) + cmd, capture_output=True, timeout=timeout, check=False)
    if proc.returncode != 0:
        raise CutError(proc.stderr.decode(errors="replace").strip()[-800:])
    return proc


def cut_to_temp(src, removed, tmp_dir, nice=10):
    """Write ``src`` minus ``removed`` spans to a temp file. Returns (tmp_path, new_duration)."""
    ext = os.path.splitext(src)[1].lower()
    muxer = MUXERS.get(ext)
    if muxer is None:
        raise CutError(f"cutting {ext} files is not supported")
    info = fingerprint.probe(src)
    duration = float(info.get("format", {}).get("duration") or 0)
    if duration <= 0:
        raise CutError("could not read duration")
    removed = normalize_spans(removed, duration)
    if not removed:
        raise CutError("nothing to remove")
    keep = keep_spans(duration, removed)
    if not keep:
        raise CutError("refusing to remove the entire file")
    expected = sum(e - s for s, e in keep)

    os.makedirs(tmp_dir, exist_ok=True)
    work = tempfile.mkdtemp(prefix="cut-", dir=tmp_dir)
    try:
        concat = os.path.join(work, "list.txt")
        with open(concat, "w") as f:
            f.write("ffconcat version 1.0\n")
            for s, e in keep:
                f.write(f"file {_concat_escape(os.path.abspath(src))}\n")
                if s > 0:
                    f.write(f"inpoint {s:.3f}\n")
                if e < duration - 0.05:
                    f.write(f"outpoint {e:.3f}\n")
        meta_text, n_chapters = _chapters_ffmetadata(info.get("chapters") or [], removed, expected)
        meta = os.path.join(work, "chapters.txt")
        with open(meta, "w") as f:
            f.write(meta_text)

        has_pic = any(st.get("codec_type") == "video" for st in info.get("streams", []))
        out = os.path.join(work, "out" + ext)
        cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y",
               "-f", "concat", "-safe", "0", "-i", concat,
               "-i", src,
               "-f", "ffmetadata", "-i", meta,
               "-map", "0:a", "-map_metadata", "1",
               "-map_chapters", "2" if n_chapters else "-1",
               "-c", "copy"]
        if has_pic:
            cmd += ["-map", "1:v", "-disposition:v", "attached_pic"]
        if muxer == "mp3":
            cmd += ["-id3v2_version", "3"]
        if muxer == "mp4":
            cmd += ["-movflags", "+faststart"]
        cmd += ["-f", muxer, out]
        _run(cmd, nice)

        new_duration = fingerprint.duration_of(out)
        if abs(new_duration - expected) > max(2.0, 0.01 * expected):
            raise CutError(f"output duration {new_duration:.1f}s, expected {expected:.1f}s")
        return out, new_duration, removed
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise


def replace_in_place(dst, src_tmp):
    """Overwrite ``dst``'s contents with ``src_tmp`` keeping its inode, owner and mode."""
    shutil.copyfile(src_tmp, dst)
    shutil.rmtree(os.path.dirname(src_tmp), ignore_errors=True)


def backup(src, originals_dir, episode_id):
    os.makedirs(originals_dir, exist_ok=True)
    dest = os.path.join(originals_dir, f"{episode_id}{os.path.splitext(src)[1].lower()}")
    shutil.copy2(src, dest)
    return dest

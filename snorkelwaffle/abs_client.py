"""Minimal Audiobookshelf API client: find libraries and trigger scans."""

import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger(__name__)


class AbsClient:
    def __init__(self, url, token, library_id=""):
        self.url = url.rstrip("/")
        self.token = token
        self.library_id = library_id

    @property
    def configured(self):
        return bool(self.url and self.token)

    def _req(self, method, path, timeout=20):
        req = urllib.request.Request(self.url + path, method=method,
                                     headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
        return json.loads(body) if body.strip().startswith(b"{") else {}

    def libraries_for(self, paths):
        """Library ids whose folders contain any of ``paths``."""
        if self.library_id:
            return [self.library_id]
        data = self._req("GET", "/api/libraries")
        ids = []
        for lib in data.get("libraries", []):
            folders = [f.get("fullPath", "").rstrip("/") for f in lib.get("folders", [])]
            if any(p == f or p.startswith(f + "/") for p in paths for f in folders if f):
                ids.append(lib["id"])
        return ids

    def scan_for(self, paths):
        """Trigger a scan of each library holding ``paths``. Returns the ids scanned."""
        if not self.configured:
            return []
        try:
            ids = self.libraries_for(list(paths))
            for lib_id in ids:
                self._req("POST", f"/api/libraries/{lib_id}/scan")
            return ids
        except (urllib.error.URLError, OSError, ValueError) as exc:
            log.warning("Audiobookshelf rescan failed: %s", exc)
            return []

    def ping(self):
        try:
            data = self._req("GET", "/api/libraries")
            return True, f"{len(data.get('libraries', []))} libraries visible"
        except urllib.error.HTTPError as exc:
            return False, f"HTTP {exc.code}"
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return False, str(exc)

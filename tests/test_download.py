"""Tests for ingest/download.py against a fake HDX API (no network)."""
import pytest
import requests

from ingest import download as dl
from ingest.sources import Source

SRC = Source("rainfall", "ken-rainfall-subnat-full.csv", "https://example/",
             hdx_dataset="ken-rainfall-subnational")


class FakeResponse:
    def __init__(self, json_body=None, content=b"", status=200):
        self._json, self._content, self.status_code = json_body, content, status

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=1):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")
        yield self._content

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_hdx(monkeypatch, resources, files):
    def get(url, params=None, **kwargs):
        if url == dl.HDX_API:
            return FakeResponse({"success": True, "result": {"resources": resources}})
        return FakeResponse(content=files.get(url, b""), status=200 if url in files else 404)
    monkeypatch.setattr(dl.requests, "get", get)


@pytest.fixture(autouse=True)
def tmp_raw(monkeypatch, tmp_path):
    monkeypatch.setattr(dl, "RAW_DOWNLOAD", tmp_path)
    return tmp_path


def test_downloads_the_matching_file(monkeypatch, tmp_raw):
    fake_hdx(monkeypatch,
             [{"name": "ken-rainfall-subnat-5ytd.csv", "url": "https://hdx/5y.csv"},
              {"name": "ken-rainfall-subnat-full.csv", "url": "https://hdx/full.csv"}],
             {"https://hdx/full.csv": b"date,rfh\n2026-09-01,1\n"})
    path = dl.download(SRC)
    assert path == tmp_raw / "ken-rainfall-subnat-full.csv"
    assert path.read_bytes().startswith(b"date,rfh")
    assert not list(tmp_raw.glob("*.part"))


def test_matches_on_the_url_file_name_when_the_title_differs(monkeypatch):
    fake_hdx(monkeypatch,
             [{"name": "Kenya rainfall (full history)", "url": "https://hdx/x/ken-rainfall-subnat-full.csv"}],
             {"https://hdx/x/ken-rainfall-subnat-full.csv": b"ok"})
    assert dl.download(SRC).read_bytes() == b"ok"


def test_a_renamed_file_fails_and_lists_what_the_dataset_has(monkeypatch):
    fake_hdx(monkeypatch, [{"name": "ken-rainfall-subnat-v2.csv", "url": "https://hdx/v2.csv"}], {})
    with pytest.raises(RuntimeError, match="ken-rainfall-subnat-v2.csv"):
        dl.download(SRC)


def test_failed_or_empty_download_leaves_no_file(monkeypatch, tmp_raw):
    fake_hdx(monkeypatch, [{"name": "ken-rainfall-subnat-full.csv", "url": "https://hdx/full.csv"}],
             {"https://hdx/full.csv": b""})
    with pytest.raises(RuntimeError, match="empty"):
        dl.download(SRC)
    fake_hdx(monkeypatch, [{"name": "ken-rainfall-subnat-full.csv", "url": "https://hdx/missing.csv"}], {})
    with pytest.raises(requests.HTTPError):
        dl.download(SRC)
    assert not (tmp_raw / "ken-rainfall-subnat-full.csv").exists()
    assert not list(tmp_raw.glob("*.part"))

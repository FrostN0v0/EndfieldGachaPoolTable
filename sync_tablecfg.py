import json
import tempfile
from pathlib import Path

import httpx
from loguru import logger

BASE_DIR = Path(__file__).parent
TABLE_DIR = BASE_DIR / "TableCfg"
STATE_PATH = BASE_DIR / ".github" / "tablecfg-sync-state.json"
REMOTE_BASE_URL = "https://lulush.microgg.cn/BeyondUID/TableCfg"
TABLE_FILES = ("GachaCharPoolTable.json", "GachaWeaponPoolTable.json")
METADATA_KEYS = ("last_modified", "etag", "content_length")
TIMEOUT = 30.0


class RemoteFileError(RuntimeError):
    pass


def load_state() -> dict[str, dict[str, str | None]]:
    if not STATE_PATH.exists():
        return {}
    data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RemoteFileError(f"同步状态文件格式无效：{STATE_PATH}")
    return data


def save_state(state: dict[str, dict[str, str | None]]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def metadata_from_headers(headers) -> dict[str, str | None]:
    return {
        "last_modified": headers.get("last-modified"),
        "etag": headers.get("etag"),
        "content_length": headers.get("content-length"),
    }


def has_reliable_metadata(metadata: dict[str, str | None]) -> bool:
    return bool(metadata["last_modified"] or metadata["etag"])


def metadata_matches_cache(
    metadata: dict[str, str | None],
    cached_metadata: dict[str, str | None] | None,
    target_path: Path,
) -> bool:
    if not cached_metadata or not target_path.exists() or not has_reliable_metadata(metadata):
        return False
    return all(metadata[key] == cached_metadata.get(key) for key in METADATA_KEYS)


def fetch_metadata(client, filename: str) -> dict[str, str | None]:
    url = f"{REMOTE_BASE_URL}/{filename}"
    response = client.head(url, follow_redirects=True)
    if response.status_code != 200:
        raise RemoteFileError(f"HEAD {url} 返回状态码 {response.status_code}")
    metadata = metadata_from_headers(response.headers)
    logger.info(
        "[{}] remote metadata: Last-Modified={}, ETag={}, Content-Length={}",
        filename,
        metadata["last_modified"],
        metadata["etag"],
        metadata["content_length"],
    )
    return metadata


def download_json(client, filename: str) -> bytes:
    url = f"{REMOTE_BASE_URL}/{filename}"
    response = client.get(url, follow_redirects=True)
    if response.status_code != 200:
        raise RemoteFileError(f"GET {url} 返回状态码 {response.status_code}")
    try:
        json.loads(response.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RemoteFileError(f"{url} 下载内容不是合法 JSON") from exc
    return response.content


def display_path(path: Path) -> Path:
    try:
        return path.relative_to(BASE_DIR)
    except ValueError:
        return path


def _remove_if_exists(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("failed to remove {}: {}", display_path(path), exc)


def apply_pending_writes(pending_writes: list[tuple[Path, bytes]]) -> None:
    staged_writes: list[tuple[Path, Path, Path]] = []
    applied_writes: list[tuple[Path, Path, bool]] = []

    try:
        for target_path, content in pending_writes:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                delete=False,
                dir=target_path.parent,
                prefix=f".{target_path.name}.",
                suffix=".tmp",
            ) as tmp_file:
                tmp_file.write(content)
                tmp_path = Path(tmp_file.name)
            with tempfile.NamedTemporaryFile(
                delete=False,
                dir=target_path.parent,
                prefix=f".{target_path.name}.",
                suffix=".bak",
            ) as backup_file:
                backup_path = Path(backup_file.name)
            _remove_if_exists(backup_path)
            staged_writes.append((target_path, tmp_path, backup_path))

        for target_path, tmp_path, backup_path in staged_writes:
            had_original = target_path.exists()
            if had_original:
                target_path.replace(backup_path)
            applied_writes.append((target_path, backup_path, had_original))
            tmp_path.replace(target_path)
            logger.info("updated {}", display_path(target_path))
    except Exception:
        for target_path, backup_path, had_original in reversed(applied_writes):
            try:
                if had_original and backup_path.exists():
                    backup_path.replace(target_path)
                elif not had_original:
                    _remove_if_exists(target_path)
            except OSError as exc:
                logger.warning("failed to restore {}: {}", display_path(target_path), exc)
        raise
    finally:
        for target_path, tmp_path, backup_path in staged_writes:
            _remove_if_exists(tmp_path)
            _remove_if_exists(backup_path)


def sync_with_client(client) -> bool:
    state = load_state()
    new_state = dict(state)
    pending_writes: list[tuple[Path, bytes]] = []

    for filename in TABLE_FILES:
        target_path = TABLE_DIR / filename
        metadata = fetch_metadata(client, filename)
        new_state[filename] = metadata

        if metadata_matches_cache(metadata, state.get(filename), target_path):
            logger.info("[{}] metadata unchanged, skip download", filename)
            continue

        content = download_json(client, filename)
        if target_path.exists() and target_path.read_bytes() == content:
            logger.info("[{}] content unchanged", filename)
            continue

        pending_writes.append((target_path, content))

    apply_pending_writes(pending_writes)

    if new_state != state or not STATE_PATH.exists():
        save_state(new_state)
        logger.info("updated {}", display_path(STATE_PATH))

    return bool(pending_writes)


def sync_tablecfg(client: httpx.Client | None = None) -> bool:
    if client is not None:
        return sync_with_client(client)
    with httpx.Client(timeout=TIMEOUT) as real_client:
        return sync_with_client(real_client)


def main() -> None:
    changed = sync_tablecfg()
    if changed:
        logger.success("TableCfg updated")
    else:
        logger.success("TableCfg already up to date")


if __name__ == "__main__":
    main()

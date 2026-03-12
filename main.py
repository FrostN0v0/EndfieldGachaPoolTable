import json
import asyncio
from pathlib import Path

import httpx
from loguru import logger

BASE_DIR = Path(__file__).parent
TABLE_DIR = BASE_DIR / "TableCfg"
RAW_DIR = BASE_DIR / "raw"
BANNER_DIR = BASE_DIR / "banner"
ROTATE_DIR = BASE_DIR / "rotate"
MAX_CONCURRENCY = 5


async def get_ef_gacha_content(
    client: httpx.AsyncClient,
    pool_id: str,
    semaphore: asyncio.Semaphore,
    server_id: str = "1",
):
    """获取终末地卡池内容（UP角色/武器信息）

    Args:
        client: httpx 异步客户端。
        pool_id: 卡池ID（如 special_xxx）。
        semaphore: 并发限制信号量。
        server_id: 服务器ID，默认为 "1"。
    """
    content_url = "https://ef-webview.hypergryph.com/api/content"
    query_params = {
        "pool_id": pool_id,
        "server_id": server_id,
        "lang": "zh-cn",
    }
    try:
        async with semaphore:
            response = await client.get(content_url, params=query_params)
        resp_json = response.json()
        code = resp_json.get("code")
        if code != 0:
            logger.warning("[{}] 请求失败，状态码：{}，消息：{}", pool_id, code, resp_json.get("message"))
            return
        # 保存到 raw 文件夹
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        out_path = RAW_DIR / f"{pool_id}.json"
        out_path.write_text(json.dumps(resp_json, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("[{}] 请求成功，已保存到 {}", pool_id, out_path.relative_to(BASE_DIR))
    except httpx.RequestError as e:
        logger.error("[{}] 请求过程中发生错误：{}", pool_id, e)


def collect_pool_ids() -> list[str]:
    """从 TableCfg 中收集需要请求的 pool_id 列表。

    - GachaCharPoolTable: 仅收集 type == 0 的条目
    - GachaWeaponPoolTable: 收集全部条目
    """
    pool_ids: list[str] = []

    # 角色池：仅 type == 0
    char_table_path = TABLE_DIR / "GachaCharPoolTable.json"
    with open(char_table_path, encoding="utf-8") as f:
        char_table: dict = json.load(f)
    for pool_id, pool_data in char_table.items():
        if pool_data.get("type") == "Special":
            pool_ids.append(pool_id)

    # 武器池：全部
    weapon_table_path = TABLE_DIR / "GachaWeaponPoolTable.json"
    with open(weapon_table_path, encoding="utf-8") as f:
        weapon_table: dict = json.load(f)
    for pool_id in weapon_table:
        pool_ids.append(pool_id)

    return pool_ids


def merge_raw_to_gacha_pool_table():
    """将 raw 文件夹下所有 JSON 整合为 GachaPoolTable.json。

    以 pool_id（文件名去掉 .json）为键名，仅存储 data.pool 的值。
    """
    merged: dict = {}
    for raw_file in sorted(RAW_DIR.glob("*.json")):
        pool_id = raw_file.stem
        with open(raw_file, encoding="utf-8") as f:
            data = json.load(f)
        pool_data = data.get("data", {}).get("pool")
        if pool_data:
            merged[pool_id] = pool_data

    out_path = BASE_DIR / "GachaPoolTable.json"
    out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("已整合 {} 个卡池到 {}", len(merged), out_path.relative_to(BASE_DIR))
    return merged


async def download_images(
    client: httpx.AsyncClient,
    merged: dict,
    semaphore: asyncio.Semaphore,
):
    """下载所有卡池的 banner 和 rotate 图片。

    banner: 根据 pool_gacha_type 分别存储到 banner/char 和 banner/weapon。
    rotate: 仅角色池有，存储到 rotate/ 文件夹。
    """
    char_dir = BANNER_DIR / "char"
    weapon_dir = BANNER_DIR / "weapon"
    char_dir.mkdir(parents=True, exist_ok=True)
    weapon_dir.mkdir(parents=True, exist_ok=True)
    ROTATE_DIR.mkdir(parents=True, exist_ok=True)

    tasks = []
    for pool_id, pool_data in merged.items():
        gacha_type = pool_data.get("pool_gacha_type", "")

        # 下载 banner (up6_image)
        up6_image = pool_data.get("up6_image", "")
        if up6_image:
            if gacha_type == "char":
                save_dir = char_dir
            elif gacha_type == "weapon":
                save_dir = weapon_dir
            else:
                logger.warning("[{}] 未知的 pool_gacha_type: {}，跳过", pool_id, gacha_type)
                continue
            tasks.append(_download_one(client, pool_id, up6_image, save_dir, semaphore))

        # 下载 rotate (rotate_image)，仅角色池
        if gacha_type == "char":
            rotate_image = pool_data.get("rotate_image", "")
            if rotate_image:
                tasks.append(_download_one(client, pool_id, rotate_image, ROTATE_DIR, semaphore, "rotate"))

    await asyncio.gather(*tasks)


async def _download_one(
    client: httpx.AsyncClient,
    pool_id: str,
    url: str,
    save_dir: Path,
    semaphore: asyncio.Semaphore,
    label: str = "banner",
):
    """下载单个图片。"""
    # 从 URL 提取扩展名
    ext = Path(url).suffix or ".png"
    save_path = save_dir / f"{pool_id}{ext}"
    try:
        async with semaphore:
            resp = await client.get(url)
            resp.raise_for_status()
        save_path.write_bytes(resp.content)
        logger.info("[{}] {} 已下载到 {}", pool_id, label, save_path.relative_to(BASE_DIR))
    except httpx.HTTPError as e:
        logger.error("[{}] {} 下载失败：{}", pool_id, label, e)


async def main():
    pool_ids = collect_pool_ids()
    logger.info("共收集到 {} 个卡池ID：{}", len(pool_ids), pool_ids)

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async with httpx.AsyncClient() as client:
        tasks = [get_ef_gacha_content(client, pid, semaphore) for pid in pool_ids]
        await asyncio.gather(*tasks)
        merged = merge_raw_to_gacha_pool_table()

        await download_images(client, merged, semaphore)

    logger.success("全部完成！")


if __name__ == "__main__":
    asyncio.run(main())

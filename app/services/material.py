import os
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List
from urllib.parse import urlencode

import requests
from loguru import logger
from moviepy.video.io.VideoFileClip import VideoFileClip
from PIL import Image

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoConcatMode
from app.utils import utils

# Thread-safe counter for API key rotation
_api_key_counter = 0
_api_key_lock = threading.Lock()


def _get_tls_verify() -> bool:
    # 默认开启 TLS 证书校验，防止素材搜索和下载过程被中间人篡改。
    # 仅在企业代理、自签证书等明确需要的场景下，允许用户通过
    # `config.toml` 显式设置 `tls_verify = false` 临时关闭。
    tls_verify = config.app.get("tls_verify", True)
    if isinstance(tls_verify, str):
        tls_verify = tls_verify.strip().lower() not in ("0", "false", "no", "off")

    if not tls_verify:
        logger.warning(
            "TLS certificate verification is disabled by config.app.tls_verify=false. "
            "Only use this in trusted proxy environments."
        )

    return bool(tls_verify)


def get_api_key(cfg_key: str):
    api_keys = config.app.get(cfg_key)
    if not api_keys:
        raise ValueError(
            f"\n\n##### {cfg_key} is not set #####\n\nPlease set it in the config.toml file: {config.config_file}\n\n"
            f"{utils.to_json(config.app)}"
        )

    # if only one key is provided, return it
    if isinstance(api_keys, str):
        return api_keys

    global _api_key_counter
    with _api_key_lock:
        _api_key_counter += 1
        return api_keys[_api_key_counter % len(api_keys)]


def _select_pexels_video_file(video_files, video_aspect: VideoAspect):
    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()
    target_ratio = video_width / video_height
    fast_mode = bool(config.app.get("fast_video_materials", True))
    if fast_mode:
        preferred_short_side = int(config.app.get("material_preferred_short_side", 720))
        if aspect == VideoAspect.portrait:
            preferred_width = preferred_short_side
            preferred_height = int(preferred_width / target_ratio)
        elif aspect == VideoAspect.landscape:
            preferred_height = preferred_short_side
            preferred_width = int(preferred_height * target_ratio)
        else:
            preferred_width = preferred_height = preferred_short_side
    else:
        preferred_width, preferred_height = video_width, video_height
    target_area = preferred_width * preferred_height
    candidates = []

    for video_file in video_files:
        try:
            w = int(video_file.get("width") or 0)
            h = int(video_file.get("height") or 0)
        except (TypeError, ValueError):
            continue

        if w < 480 or h < 480:
            continue
        if aspect == VideoAspect.portrait and h < w:
            continue
        if aspect == VideoAspect.landscape and w < h:
            continue
        if aspect == VideoAspect.square and abs(w - h) / max(w, h) > 0.25:
            continue

        ratio = w / h
        under_target = 0 if w >= preferred_width and h >= preferred_height else 1
        over_large = 1 if fast_mode and (w > preferred_width * 1.8 or h > preferred_height * 1.8) else 0
        area_delta = abs((w * h) - target_area)
        candidates.append((under_target, over_large, abs(ratio - target_ratio), area_delta, video_file))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[:4])
    return candidates[0][4]


def search_videos_pexels(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)
    video_orientation = aspect.name
    video_width, video_height = aspect.to_resolution()
    api_key = get_api_key("pexels_api_keys")
    headers = {
        "Authorization": api_key,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    }
    # Build URL
    params = {
        "query": search_term,
        "per_page": int(config.app.get("material_search_per_page", 12)),
        "orientation": video_orientation,
    }
    query_url = f"https://api.pexels.com/videos/search?{urlencode(params)}"
    logger.info(f"searching videos: {query_url}, with proxies: {config.proxy}")

    try:
        r = requests.get(
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(30, 60),
        )
        response = r.json()
        video_items = []
        if "videos" not in response:
            logger.error(f"search videos failed: {response}")
            return video_items
        videos = response["videos"]
        # loop through each video in the result
        for v in videos:
            duration = v["duration"]
            # check if video has desired minimum duration
            if duration < minimum_duration:
                continue
            video_files = v["video_files"]
            video = _select_pexels_video_file(video_files, aspect)
            if video:
                item = MaterialInfo()
                item.provider = "pexels_video"
                item.url = video["link"]
                item.duration = duration
                video_items.append(item)
        return video_items
    except Exception as e:
        logger.error(f"search videos failed: {str(e)}")

    return []


def search_images_pexels(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)
    image_orientation = aspect.name
    api_key = get_api_key("pexels_api_keys")
    headers = {
        "Authorization": api_key,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    }
    params = {
        "query": search_term,
        "per_page": int(config.app.get("material_search_per_page", 12)),
        "orientation": image_orientation,
    }
    query_url = f"https://api.pexels.com/v1/search?{urlencode(params)}"
    logger.info(f"searching images: {query_url}, with proxies: {config.proxy}")

    try:
        r = requests.get(
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(30, 60),
        )
        response = r.json()
        image_items = []
        if "photos" not in response:
            logger.error(f"search images failed: {response}")
            return image_items

        for photo in response["photos"]:
            try:
                width = int(photo.get("width") or 0)
                height = int(photo.get("height") or 0)
            except (TypeError, ValueError):
                continue
            if width < 480 or height < 480:
                continue

            src = photo.get("src") or {}
            image_url = (
                src.get("large2x")
                or src.get("large")
                or src.get("original")
                or src.get("medium")
            )
            if not image_url:
                continue

            item = MaterialInfo()
            item.provider = "pexels_image"
            item.url = image_url
            item.duration = minimum_duration
            image_items.append(item)
        return image_items
    except Exception as e:
        logger.error(f"search images failed: {str(e)}")

    return []


def search_videos_pixabay(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)

    video_width, video_height = aspect.to_resolution()

    api_key = get_api_key("pixabay_api_keys")
    # Build URL
    params = {
        "q": search_term,
        "video_type": "all",  # Accepted values: "all", "film", "animation"
        "per_page": 50,
        "key": api_key,
    }
    query_url = f"https://pixabay.com/api/videos/?{urlencode(params)}"
    logger.info(f"searching videos: {query_url}, with proxies: {config.proxy}")

    try:
        r = requests.get(
            query_url, proxies=config.proxy, verify=_get_tls_verify(), timeout=(30, 60)
        )
        response = r.json()
        video_items = []
        if "hits" not in response:
            logger.error(f"search videos failed: {response}")
            return video_items
        videos = response["hits"]
        # loop through each video in the result
        for v in videos:
            duration = v["duration"]
            # check if video has desired minimum duration
            if duration < minimum_duration:
                continue
            video_files = v["videos"]
            # loop through each url to determine the best quality
            for video_type in video_files:
                video = video_files[video_type]
                w = int(video["width"])
                # h = int(video["height"])
                if w >= video_width:
                    item = MaterialInfo()
                    item.provider = "pixabay"
                    item.url = video["url"]
                    item.duration = duration
                    video_items.append(item)
                    break
        return video_items
    except Exception as e:
        logger.error(f"search videos failed: {str(e)}")

    return []


def save_image(image_url: str, save_dir: str = "") -> str:
    if not save_dir:
        save_dir = utils.storage_dir("local_videos")

    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    url_without_query = image_url.split("?")[0]
    url_hash = utils.md5(url_without_query)
    image_ext = os.path.splitext(url_without_query)[1].lower()
    if image_ext not in (".jpg", ".jpeg", ".png", ".bmp"):
        image_ext = ".jpg"
    image_path = f"{save_dir}/img-{url_hash}{image_ext}"

    if os.path.exists(image_path) and os.path.getsize(image_path) > 0:
        logger.info(f"image already exists: {image_path}")
        return image_path

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    response = requests.get(
        image_url,
        headers=headers,
        proxies=config.proxy,
        verify=_get_tls_verify(),
        timeout=(60, 240),
    )
    response.raise_for_status()

    with open(image_path, "wb") as f:
        f.write(response.content)

    try:
        with Image.open(image_path) as img:
            img.verify()
        return image_path
    except Exception as e:
        logger.warning(f"invalid image file: {image_path} => {str(e)}")
        try:
            os.remove(image_path)
        except Exception as remove_error:
            logger.warning(
                f"failed to remove invalid image file: {image_path}, error: {str(remove_error)}"
            )
        return ""


def save_video(video_url: str, save_dir: str = "") -> str:
    if not save_dir:
        save_dir = utils.storage_dir("cache_videos")

    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    url_without_query = video_url.split("?")[0]
    url_hash = utils.md5(url_without_query)
    video_id = f"vid-{url_hash}"
    video_path = f"{save_dir}/{video_id}.mp4"

    # if video already exists, return the path
    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        logger.info(f"video already exists: {video_path}")
        return video_path
    if os.path.exists(video_path):
        os.remove(video_path)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }

    # if video does not exist, download it
    try:
        response = requests.get(
            video_url,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(60, 240),
        )
        response.raise_for_status()
        with open(video_path, "wb") as f:
            f.write(response.content)
    except Exception as e:
        logger.warning(f"failed to download video file: {video_url} => {str(e)}")
        if os.path.exists(video_path):
            try:
                os.remove(video_path)
            except Exception as remove_error:
                logger.warning(
                    f"failed to remove incomplete video file: {video_path}, error: {str(remove_error)}"
                )
        return ""

    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        clip = None
        try:
            clip = VideoFileClip(video_path)
            duration = clip.duration
            fps = clip.fps
            if duration > 0 and fps > 0:
                return video_path
        except Exception as e:
            logger.warning(f"invalid video file: {video_path} => {str(e)}")
            try:
                os.remove(video_path)
            except Exception as remove_error:
                logger.warning(
                    f"failed to remove invalid video file: {video_path}, error: {str(remove_error)}"
                )
        finally:
            if clip is not None:
                try:
                    clip.close()
                except Exception as close_error:
                    logger.warning(
                        f"failed to close video clip: {video_path}, error: {str(close_error)}"
                    )
    return ""


def convert_image_to_video(image_path: str, clip_duration: int) -> str:
    from app.services import video

    material_info = MaterialInfo(provider="local", url=image_path, duration=clip_duration)
    processed_materials = video.preprocess_video(
        [material_info], clip_duration=clip_duration
    )
    if not processed_materials:
        return ""
    return processed_materials[0].url


def download_videos(
    task_id: str,
    search_terms: List[str],
    source: str = "pexels",
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_contact_mode: VideoConcatMode = VideoConcatMode.random,
    audio_duration: float = 0.0,
    max_clip_duration: int = 5,
) -> List[str]:
    valid_video_items = []
    valid_video_urls = []
    found_duration = 0.0
    search_videos = search_videos_pexels
    if source == "pixabay":
        search_videos = search_videos_pixabay

    def add_materials(items: List[MaterialInfo]):
        nonlocal found_duration
        for item in items:
            if item.url not in valid_video_urls:
                valid_video_items.append(item)
                valid_video_urls.append(item.url)
                found_duration += item.duration

    def search_many(search_func, label: str):
        terms = [str(term).strip() for term in search_terms if str(term).strip()]
        if not terms:
            return

        worker_count = min(4, len(terms))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_term = {
                executor.submit(
                    search_func,
                    search_term=term,
                    minimum_duration=max_clip_duration,
                    video_aspect=video_aspect,
                ): term
                for term in terms
            }
            for future in as_completed(future_to_term):
                term = future_to_term[future]
                try:
                    material_items = future.result()
                except Exception as exc:
                    logger.error(f"search {label} failed for '{term}': {str(exc)}")
                    continue
                logger.info(f"found {len(material_items)} {label} for '{term}'")
                add_materials(material_items)

    search_many(search_videos, "videos")

    # Pexels photos are a quality fallback. Search them only if video results cannot
    # cover the requested duration, which avoids extra network calls on healthy runs.
    if source == "pexels" and found_duration < audio_duration:
        logger.info(
            f"video duration is not enough ({found_duration:.1f}s/{audio_duration:.1f}s), "
            "searching Pexels images as fallback"
        )
        search_many(search_images_pexels, "images")

    logger.info(
        f"found total videos: {len(valid_video_items)}, required duration: {audio_duration} seconds, found duration: {found_duration} seconds"
    )
    video_paths = []

    material_directory = config.app.get("material_directory", "").strip()
    if material_directory == "task":
        material_directory = utils.task_dir(task_id)
    elif material_directory and not os.path.isdir(material_directory):
        material_directory = ""

    concat_mode_value = getattr(video_contact_mode, "value", video_contact_mode)
    if concat_mode_value == VideoConcatMode.random.value:
        random.shuffle(valid_video_items)

    def download_material(item: MaterialInfo) -> tuple[MaterialInfo, str]:
        try:
            logger.info(f"downloading material from {item.provider}: {item.url}")
            if item.provider == "pexels_image":
                image_dir = utils.storage_dir("local_videos", create=True)
                saved_image_path = save_image(image_url=item.url, save_dir=image_dir)
                saved_video_path = (
                    convert_image_to_video(saved_image_path, max_clip_duration)
                    if saved_image_path
                    else ""
                )
            else:
                saved_video_path = save_video(
                    video_url=item.url, save_dir=material_directory
                )
        except Exception as e:
            logger.error(f"failed to download video: {utils.to_json(item)} => {str(e)}")
            return item, ""

        return item, saved_video_path

    total_duration = 0.0
    next_item_index = 0
    max_download_workers = min(3, max(1, len(valid_video_items)))
    pending_downloads = {}

    with ThreadPoolExecutor(max_workers=max_download_workers) as executor:
        while next_item_index < len(valid_video_items) and len(pending_downloads) < max_download_workers:
            item = valid_video_items[next_item_index]
            pending_downloads[executor.submit(download_material, item)] = item
            next_item_index += 1

        while pending_downloads:
            for future in as_completed(pending_downloads):
                pending_downloads.pop(future, None)
                item, saved_video_path = future.result()

                if saved_video_path:
                    logger.info(f"video saved: {saved_video_path}")
                    video_paths.append(saved_video_path)
                    seconds = min(max_clip_duration, item.duration)
                    total_duration += seconds

                if total_duration > audio_duration:
                    logger.info(
                        f"total duration of downloaded videos: {total_duration} seconds, skip downloading more"
                    )
                    pending_downloads.clear()
                    break

                if next_item_index < len(valid_video_items):
                    next_item = valid_video_items[next_item_index]
                    pending_downloads[executor.submit(download_material, next_item)] = next_item
                    next_item_index += 1

                break

    logger.success(f"downloaded {len(video_paths)} videos")
    return video_paths


if __name__ == "__main__":
    download_videos(
        "test123", ["Money Exchange Medium"], audio_duration=100, source="pixabay"
    )

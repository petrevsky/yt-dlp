import base64
import os.path
import re
import json

from .common import InfoExtractor
from ..compat import compat_urllib_parse_unquote
from ..utils import (
    ExtractorError,
    update_url_query,
    url_basename,
    urlencode_postdata,
    unified_strdate,
)


class DropboxIE(InfoExtractor):
    _VALID_URL = r"https?://(?:www\.)?dropbox\.com/(?:(?:e/)?scl/fi|sh?)/(?P<id>\w+)"
    _TESTS = [
        {
            "url": "https://www.dropbox.com/s/nelirfsxnmcfbfh/youtube-dl%20test%20video%20%27%C3%A4%22BaW_jenozKc.mp4?dl=0",
            "info_dict": {
                "id": "nelirfsxnmcfbfh",
                "ext": "mp4",
                "title": "youtube-dl test video 'ä\"BaW_jenozKc",
            },
        },
        {
            "url": "https://www.dropbox.com/s/nelirfsxnmcfbfh",
            "only_matching": True,
        },
        {
            "url": "https://www.dropbox.com/sh/2mgpiuq7kv8nqdf/AABy-fW4dkydT4GmWi2mdOUDa?dl=0&preview=Drone+Shot.mp4",
            "only_matching": True,
        },
        {
            "url": "https://www.dropbox.com/scl/fi/r2kd2skcy5ylbbta5y1pz/DJI_0003.MP4?dl=0&rlkey=wcdgqangn7t3lnmmv6li9mu9h",
            "only_matching": True,
        },
        {
            "url": "https://www.dropbox.com/e/scl/fi/r2kd2skcy5ylbbta5y1pz/DJI_0003.MP4?dl=0&rlkey=wcdgqangn7t3lnmmv6li9mu9h",
            "only_matching": True,
        },
    ]

    def _real_extract(self, url):
        mobj = self._match_valid_url(url)
        video_id = mobj.group("id")
        webpage = self._download_webpage(url, video_id)
        fn = compat_urllib_parse_unquote(url_basename(url))
        title = os.path.splitext(fn)[0]

        password = self.get_param("videopassword")
        if (
            self._og_search_title(webpage) == "Dropbox - Password Required"
            or "Enter the password for this link" in webpage
        ):

            if password:
                content_id = self._search_regex(
                    r'content_id=(.*?)["\']', webpage, "content_id"
                )
                payload = f'is_xhr=true&t={self._get_cookies("https://www.dropbox.com").get("t").value}&content_id={content_id}&password={password}&url={url}'
                response = self._download_json(
                    "https://www.dropbox.com/sm/auth",
                    video_id,
                    "POSTing video password",
                    data=payload.encode("UTF-8"),
                    headers={
                        "content-type": "application/x-www-form-urlencoded; charset=UTF-8"
                    },
                )

                if response.get("status") != "authed":
                    raise ExtractorError("Authentication failed!", expected=True)
                webpage = self._download_webpage(url, video_id)
            elif self._get_cookies("https://dropbox.com").get("sm_auth"):
                webpage = self._download_webpage(url, video_id)
            else:
                raise ExtractorError(
                    "Password protected video, use --video-password <password>",
                    expected=True,
                )

        formats, subtitles, has_anonymous_download = [], {}, False
        thumbnails = []
        storyboard_url, thumbnail_url, video_internal_id = None, None, None

        for encoded in reversed(
            re.findall(
                r'registerStreamedPrefetch\s*\(\s*"[\w/+=]+"\s*,\s*"([\w/+=]+)"',
                webpage,
            )
        ):
            decoded = base64.b64decode(encoded).decode("utf-8", "ignore")

            transcode_url = self._search_regex(
                r"\n.(https://[^\x03\x08\x12\n]+\.m3u8)",
                decoded,
                "transcode url",
                default=None,
            )

            if not transcode_url:
                continue
            formats, subtitles = self._extract_m3u8_formats_and_subtitles(
                transcode_url, video_id, "mp4"
            )
            has_anonymous_download = self._search_regex(
                r"(anonymous:\tanonymous)", decoded, "anonymous", default=False
            )
            thumbnail_url = self._search_regex(
                r"(https://(?![^\s]*?scrubber_thumb_vtt[^\s]*?).+?thumb[^\s]*?\.jpeg)",
                decoded,
                "thumbnail url",
                default=None,
            )

            storyboard_url = self._search_regex(
                r"(https://(?![^\s]*?hls[^\s]*?).+?scrubber_thumb_vtt[^\s]*?\.vtt)",
                decoded,
                "vtt url",
                default=None,
            )

            video_internal_id = self._search_regex(
                r"id:(\S+)", decoded, "video id", default=None
            )

            break

        if thumbnail_url:
            sizes = [
                ["480x320", 480, 320],
                ["640x480", 640, 480],
                ["800x600", 800, 600],
                ["1024x768", 1024, 768],
                ["1280x960", 1280, 960],
                ["1600x1200", 1600, 1200],
                ["2048x1536", 2048, 1536],
            ]

            for size in sizes:
                preference = -1
                if size[1] == 1280:
                    preference = 1
                thumbnails.append(
                    {
                        "url": update_url_query(
                            thumbnail_url, {"size": size[0], "size_mode": "2"}
                        ),
                        "width": size[1],
                        "height": size[2],
                        "preference": preference,
                    }
                )

        additional_metadata = {}

        if video_internal_id:
            # get cookies
            cookies = self._get_cookies("https://www.dropbox.com")

            headers = {
                "Accept": "application/json",
                "content-type": "application/json; charset=utf-8",
                "x-csrf-token": cookies.get("t").value,
                "x-dropbox-uid": "-1",
            }

            payload = {"file_path_or_id": f"id:{video_internal_id}", "url": url}

            # make post request to get the file metadata
            json_result = self._download_json(
                "https://www.dropbox.com/2/files/get_file_content_metadata",
                video_id,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                fatal=False,
            )

            if json_result:
                additional_metadata = json_result.get("metadata", {})

        # downloads enabled we can get the original file
        if has_anonymous_download:
            formats.append(
                {
                    "url": update_url_query(url, {"dl": "1"}),
                    "format_id": "original",
                    "format_note": "Original",
                    "quality": 1,
                    "width": additional_metadata.get("resolution_width", None),
                    "height": additional_metadata.get("resolution_height", None),
                    "fps": additional_metadata.get("frame_rate", None),
                    "vcodec": additional_metadata.get("codec", None),
                }
            )

        return {
            "id": video_id,
            "title": title,
            "formats": formats,
            "subtitles": subtitles,
            "thumbnails": thumbnails,
            "storyboard_url": storyboard_url,
            "duration": additional_metadata.get("duration", None),
            "upload_date": unified_strdate(
                additional_metadata.get("capture_date", None)
            ),
        }

from urllib.parse import quote, urljoin, urlsplit

import httpx
from starlette.background import BackgroundTask
from starlette.responses import RedirectResponse, Response, StreamingResponse

from app.core.config import settings
from app.core.exceptions import AppError


class GitHubReleaseStorageService:
    api_base_url = "https://api.github.com"

    def __init__(self) -> None:
        self.repository = settings.github_release_repository
        self.token = settings.github_release_token

    def _configuration(self) -> tuple[str, str, str]:
        if self.repository is None or self.token is None:
            raise AppError(
                "RELEASE_STORAGE_UNAVAILABLE",
                "GitHub release storage is not configured.",
                503,
            )
        owner, repository = self.repository.split("/", maxsplit=1)
        return owner, repository, self.token.get_secret_value()

    async def verify_asset(self, asset_id: int) -> tuple[str, int]:
        owner, repository, token = self._configuration()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                response = await client.get(
                    self._asset_url(owner, repository, asset_id),
                    headers=self._headers(token, "application/vnd.github+json"),
                )
        except httpx.RequestError as exc:
            raise self._unavailable("Could not verify the APK in GitHub.") from exc

        if response.status_code == 404:
            raise AppError(
                "RELEASE_FILE_NOT_FOUND",
                "The APK was not found in the configured private GitHub repository.",
                404,
            )
        if response.status_code != 200:
            raise self._unavailable(
                "Could not verify the APK in GitHub."
            )

        try:
            metadata = response.json()
            name = metadata["name"]
            size = metadata["size"]
            state = metadata["state"]
            returned_id = metadata["id"]
        except (ValueError, KeyError, TypeError) as exc:
            raise self._unavailable(
                "GitHub returned invalid APK metadata."
            ) from exc

        if (
            returned_id != asset_id
            or state != "uploaded"
            or not self._is_apk_name(name)
            or not isinstance(size, int)
            or size <= 0
            or size > 2_147_483_647
        ):
            raise AppError(
                "RELEASE_FILE_INVALID",
                "The GitHub release asset is not a valid uploaded APK.",
                422,
            )
        return name, size

    async def create_download_response(
        self,
        asset_id: int,
        *,
        file_name: str,
    ) -> Response:
        owner, repository, token = self._configuration()
        client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
        request = client.build_request(
            "GET",
            self._asset_url(owner, repository, asset_id),
            headers=self._headers(token, "application/octet-stream"),
        )
        try:
            response = await client.send(request, stream=True)
        except httpx.RequestError as exc:
            await client.aclose()
            raise self._unavailable("Could not prepare the APK download.") from exc

        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location")
            await response.aclose()
            await client.aclose()
            if not location:
                raise self._unavailable(
                    "GitHub did not provide an APK download location."
                )
            download_url = urljoin(str(response.request.url), location)
            parsed_url = urlsplit(download_url)
            if (
                parsed_url.scheme != "https"
                or not parsed_url.hostname
                or not (
                    parsed_url.hostname == "github.com"
                    or parsed_url.hostname.endswith(".githubusercontent.com")
                )
                or parsed_url.username is not None
                or parsed_url.password is not None
            ):
                raise self._unavailable(
                    "GitHub returned an invalid APK download location."
                )
            return RedirectResponse(
                url=download_url,
                status_code=303,
                headers={"Cache-Control": "no-store"},
            )

        if response.status_code == 200:
            content_type = response.headers.get("content-type", "").split(";", 1)[0]
            if content_type and content_type not in {
                "application/octet-stream",
                "application/vnd.android.package-archive",
            }:
                await response.aclose()
                await client.aclose()
                raise self._unavailable(
                    "GitHub returned an invalid APK download response."
                )
            headers = {
                "Cache-Control": "no-store",
                "Content-Disposition": (
                    f"attachment; filename*=UTF-8''{quote(file_name, safe='')}"
                ),
            }
            async def close_stream() -> None:
                await response.aclose()
                await client.aclose()

            return StreamingResponse(
                response.aiter_bytes(),
                media_type="application/vnd.android.package-archive",
                headers=headers,
                background=BackgroundTask(close_stream),
            )

        await response.aclose()
        await client.aclose()
        if response.status_code == 404:
            raise AppError(
                "RELEASE_FILE_NOT_FOUND",
                "The APK is no longer available in GitHub.",
                404,
            )
        raise self._unavailable("Could not prepare the APK download.")

    @classmethod
    def _asset_url(cls, owner: str, repository: str, asset_id: int) -> str:
        return (
            f"{cls.api_base_url}/repos/{quote(owner, safe='')}/"
            f"{quote(repository, safe='')}/releases/assets/{asset_id}"
        )

    @staticmethod
    def _headers(token: str, accept: str) -> dict[str, str]:
        return {
            "Accept": accept,
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @staticmethod
    def _is_apk_name(value: object) -> bool:
        return (
            isinstance(value, str)
            and value.lower().endswith(".apk")
            and len(value) <= 255
            and "/" not in value
            and "\\" not in value
            and not any(ord(char) < 32 or ord(char) == 127 for char in value)
        )

    @staticmethod
    def _unavailable(message: str) -> AppError:
        return AppError("RELEASE_STORAGE_UNAVAILABLE", message, 503)

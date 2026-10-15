import hashlib
import os
import platform
import shutil
import sys
import tempfile
import webbrowser
from datetime import datetime

import png  # type: ignore[import-untyped]
import qrcode  # type: ignore[import-untyped]
from qrcode.constants import ERROR_CORRECT_M  # type: ignore[import-untyped]
from qrcode.image.pure import PyPNGImage  # type: ignore[import-untyped]
from wox_plugin import (
    ActionContext,
    Context,
    CopyParams,
    CopyType,
    LogLevel,
    Plugin,
    PluginInitParams,
    PublicAPI,
    Query,
    RefreshQueryParam,
    Result,
    ResultAction,
    ScreenshotOption,
    WoxImage,
    WoxPreview,
    WoxPreviewType,
)


def _add_platform_native_path() -> None:
    """Make the bundled native dependencies for this platform importable.

    Wox only adds <plugin>/dependencies to sys.path. Compiled wheels such as
    zxing-cpp's abi3 build share one file name (zxingcpp.abi3.so) across macOS
    and Linux, so they cannot be merged into a single directory. They live under
    dependencies/native/<platform> instead and are selected here. The keys must
    stay in sync with PLATFORMS in scripts/build_dependencies.py.
    """
    system = platform.system()
    machine = platform.machine().lower()
    arm = machine in {"arm64", "aarch64"}
    if system == "Windows":
        key = "win_arm64" if arm else "win_amd64"
    elif system == "Darwin":
        key = "macos_arm64" if arm else "macos_x86_64"
    elif system == "Linux":
        key = "linux_arm64" if arm else "linux_x86_64"
    else:
        return
    native_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dependencies", "native", key)
    if os.path.isdir(native_dir) and native_dir not in sys.path:
        sys.path.insert(0, native_dir)


_add_platform_native_path()

TITLE_MAX_LEN = 120

# Sub-command (declared in plugin.json Commands) that shows scan results only.
SCAN_COMMAND = "scan"


def _short(text: str) -> str:
    return text if len(text) <= TITLE_MAX_LEN else text[: TITLE_MAX_LEN - 3] + "..."


def image_preview_data(image: WoxImage) -> str:
    """Serialize a WoxImage for a WoxPreviewType.IMAGE preview.

    The host parses the value as "type:data" (strings.Cut on the first ":").
    Do not use str(image) here: on Python 3.12+ f-string formatting of the
    (str, Enum) image_type yields "WoxImageType.ABSOLUTE" instead of
    "absolute", which the host rejects as an unsupported image type.
    """
    return f"{image.image_type.value}:{image.image_data}"


def decode_qr_image(path: str) -> list[str]:
    """Decode all QR/barcode payloads from an image file.

    Pure function (no Wox runtime needed), so it is unit-testable.
    zxingcpp is imported here rather than at module scope so a platform without
    a bundled native build still loads the plugin and can generate QR codes.
    """
    import zxingcpp

    with open(path, "rb") as f:
        width, height, rows, _info = png.Reader(file=f).asRGBA8()
        pixels = b"".join(bytes(row) for row in rows)
    view = zxingcpp.ImageView(pixels, width, height, zxingcpp.ImageFormat.RGBA)
    barcodes = zxingcpp.read_barcodes(view)
    texts: list[str] = []
    for barcode in barcodes:
        text = (barcode.text or "").strip()
        if text and text not in texts:
            texts.append(text)
    return texts


class QRCodePlugin(Plugin):
    api: PublicAPI

    def __init__(self) -> None:
        # Decoded payloads from the latest screenshot scan, rendered by query().
        self._scan_texts: list[str] = []
        # Resolved lazily on first use; see _get_cache_dir().
        self._cache_dir: str = ""

    async def init(self, ctx: Context, init_params: PluginInitParams) -> None:
        self.api = init_params.api

    async def query(self, ctx: Context, query: Query) -> list[Result]:
        # Trigger keywords are user-editable in Wox settings, so the matched keyword
        # value must never decide the mode: renaming or deleting a dedicated scan
        # keyword would otherwise make the screenshot scan unreachable. "scan" comes
        # from plugin.json Commands (users cannot edit it), and an empty search means
        # no text was given, which is the scan case for any trigger keyword.
        command = (query.command or "").strip().lower()
        text = (query.search or "").strip()

        if command == SCAN_COMMAND:
            return self._scan_results()
        if not text:
            return self._scan_results() + await self._generate_results(ctx, "")
        return await self._generate_results(ctx, text)

    # ------------------------------------------------------------------ generate

    async def _generate_results(self, ctx: Context, text: str) -> list[Result]:
        if not text:
            return [
                Result(
                    title="i18n:input_text_title",
                    sub_title="i18n:input_text_subtitle",
                    icon=WoxImage.new_emoji("🔳"),
                )
            ]
        try:
            png_path = await self._make_qr_png(ctx, text)
        except Exception as e:  # text too long, etc.
            await self.api.log(ctx, LogLevel.ERROR, f"QR generate failed: {e}")
            return [
                Result(
                    title="i18n:generate_failed_title",
                    sub_title=str(e),
                    icon=WoxImage.new_emoji("⚠️"),
                )
            ]

        img = WoxImage.new_absolute(png_path)
        return [
            Result(
                title=_short(text),
                sub_title="i18n:qr_generated",
                icon=img,
                preview=WoxPreview(
                    preview_type=WoxPreviewType.IMAGE,
                    preview_data=image_preview_data(img),
                ),
                actions=[
                    ResultAction(
                        name="i18n:action_copy_image",
                        icon=WoxImage.new_emoji("🖼️"),
                        context_data={"png_path": png_path},
                        action=self._action_copy_image,
                    ),
                    ResultAction(
                        name="i18n:action_copy_text",
                        icon=WoxImage.new_emoji("📋"),
                        context_data={"text": text},
                        action=self._action_copy_text,
                    ),
                    ResultAction(
                        name="i18n:action_save_png",
                        icon=WoxImage.new_emoji("💾"),
                        context_data={"png_path": png_path},
                        action=self._action_save_png,
                    ),
                ],
            )
        ]

    async def _get_cache_dir(self, ctx: Context) -> str:
        """Resolve the plugin cache directory once, then reuse it.

        Wox owns ~/.wox/cache/plugins/<plugin-id>/ and deletes it when the
        plugin is uninstalled, so generated PNGs stay in the plugin's own cache
        instead of a shared temp directory. get_cache_folder() returns "" on
        failure and joining "" would drop the PNG into the process working
        directory, so fall back to a stable temp dir in that case.
        """
        if self._cache_dir:
            return self._cache_dir
        cache_dir = await self.api.get_cache_folder(ctx)
        if not cache_dir:
            cache_dir = os.path.join(tempfile.gettempdir(), "wox-qrcode")
            await self.api.log(ctx, LogLevel.WARNING, f"get_cache_folder returned empty, falling back to {cache_dir}")
        os.makedirs(cache_dir, exist_ok=True)
        self._cache_dir = cache_dir
        return cache_dir

    async def _make_qr_png(self, ctx: Context, text: str) -> str:
        cache_dir = await self._get_cache_dir(ctx)
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
        png_path = os.path.join(cache_dir, f"qr_{digest}.png")
        if not os.path.exists(png_path):
            qr = qrcode.QRCode(
                error_correction=ERROR_CORRECT_M,
                box_size=10,
                border=4,
            )
            qr.add_data(text)
            qr.make(fit=True)
            img = qr.make_image(image_factory=PyPNGImage)
            with open(png_path, "wb") as f:
                img.save(f)
        return png_path

    # ------------------------------------------------------------------ scan

    def _scan_results(self) -> list[Result]:
        results = [
            Result(
                title="i18n:scan_title",
                sub_title="i18n:scan_subtitle",
                icon=WoxImage.new_emoji("🔍"),
                actions=[
                    ResultAction(
                        name="i18n:action_start_scan",
                        icon=WoxImage.new_emoji("📸"),
                        action=self._action_scan,
                    )
                ],
            )
        ]
        for text in self._scan_texts:
            actions = [
                ResultAction(
                    name="i18n:action_copy_result",
                    icon=WoxImage.new_emoji("📋"),
                    context_data={"text": text},
                    action=self._action_copy_text,
                )
            ]
            if text.startswith(("http://", "https://")):
                actions.append(
                    ResultAction(
                        name="i18n:action_open_url",
                        icon=WoxImage.new_emoji("🌐"),
                        context_data={"text": text},
                        action=self._action_open_url,
                    )
                )
            results.append(
                Result(
                    title=_short(text),
                    sub_title="i18n:scan_result",
                    icon=WoxImage.new_emoji("✅"),
                    actions=actions,
                )
            )
        return results

    async def _action_scan(self, ctx: Context, ac: ActionContext) -> None:
        res = await self.api.screenshot(
            ctx,
            ScreenshotOption(hide_annotation_toolbar=True, auto_confirm=True),
        )
        if not res.success:
            if res.errmsg:
                msg = await self.api.get_translation(ctx, "notify_screenshot_failed")
                await self.api.notify(ctx, msg.format(res.errmsg))
            return
        try:
            texts = decode_qr_image(res.screenshot_path)
        except Exception as e:
            await self.api.log(ctx, LogLevel.ERROR, f"QR decode failed: {e}")
            msg = await self.api.get_translation(ctx, "notify_recognize_failed")
            await self.api.notify(ctx, msg.format(e))
            return
        if not texts:
            await self.api.notify(ctx, await self.api.get_translation(ctx, "notify_no_qr"))
            return
        self._scan_texts = texts
        await self.api.refresh_query(ctx, RefreshQueryParam(preserve_selected_index=False))
        await self.api.show_app(ctx)

    # ------------------------------------------------------------------ actions

    async def _action_copy_image(self, ctx: Context, ac: ActionContext) -> None:
        path = (ac.context_data or {}).get("png_path", "")
        if path:
            await self.api.copy(
                ctx,
                CopyParams(
                    type=CopyType.IMAGE,
                    wox_image=WoxImage.new_absolute(path).to_dict(),
                ),
            )

    async def _action_copy_text(self, ctx: Context, ac: ActionContext) -> None:
        text = (ac.context_data or {}).get("text", "")
        if text:
            await self.api.copy(ctx, CopyParams(type=CopyType.TEXT, text=text))

    async def _action_save_png(self, ctx: Context, ac: ActionContext) -> None:
        src = (ac.context_data or {}).get("png_path", "")
        if not src:
            return
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        os.makedirs(desktop, exist_ok=True)
        dst = os.path.join(desktop, f"qrcode_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        shutil.copyfile(src, dst)
        msg = await self.api.get_translation(ctx, "notify_saved_desktop")
        await self.api.notify(ctx, msg.format(os.path.basename(dst)))

    async def _action_open_url(self, ctx: Context, ac: ActionContext) -> None:
        url = (ac.context_data or {}).get("text", "")
        if url:
            webbrowser.open(url)


plugin = QRCodePlugin()

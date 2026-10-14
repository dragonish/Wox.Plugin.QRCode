import hashlib
import os
import shutil
import tempfile
import webbrowser
from datetime import datetime

import png  # type: ignore[import-untyped]
import qrcode  # type: ignore[import-untyped]
import zxingcpp
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

TITLE_MAX_LEN = 120


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
    """
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

    async def init(self, ctx: Context, init_params: PluginInitParams) -> None:
        self.api = init_params.api

    async def query(self, ctx: Context, query: Query) -> list[Result]:
        keyword = (query.trigger_keyword or "").lower()
        if keyword == "qrs":
            return self._scan_results()
        return await self._generate_results(ctx, (query.search or "").strip())

    # ------------------------------------------------------------------ generate

    async def _generate_results(self, ctx: Context, text: str) -> list[Result]:
        if not text:
            return [
                Result(
                    title="输入要生成二维码的文本",
                    sub_title="例如：qr https://example.com",
                    icon=WoxImage.new_emoji("🔳"),
                )
            ]
        try:
            png_path = await self._make_qr_png(ctx, text)
        except Exception as e:  # text too long, etc.
            await self.api.log(ctx, LogLevel.ERROR, f"QR generate failed: {e}")
            return [
                Result(
                    title="生成二维码失败",
                    sub_title=str(e),
                    icon=WoxImage.new_emoji("⚠️"),
                )
            ]

        img = WoxImage.new_absolute(png_path)
        return [
            Result(
                title=_short(text),
                sub_title="二维码已生成",
                icon=img,
                preview=WoxPreview(
                    preview_type=WoxPreviewType.IMAGE,
                    preview_data=image_preview_data(img),
                ),
                actions=[
                    ResultAction(
                        name="复制二维码图片",
                        icon=WoxImage.new_emoji("🖼️"),
                        context_data={"png_path": png_path},
                        action=self._action_copy_image,
                    ),
                    ResultAction(
                        name="复制文本内容",
                        icon=WoxImage.new_emoji("📋"),
                        context_data={"text": text},
                        action=self._action_copy_text,
                    ),
                    ResultAction(
                        name="保存 PNG 到桌面",
                        icon=WoxImage.new_emoji("💾"),
                        context_data={"png_path": png_path},
                        action=self._action_save_png,
                    ),
                ],
            )
        ]

    async def _make_qr_png(self, ctx: Context, text: str) -> str:
        # wox-plugin 0.0.81 has no get_cache_folder(); use a stable temp dir instead.
        cache_dir = os.path.join(tempfile.gettempdir(), "wox-qrcode")
        os.makedirs(cache_dir, exist_ok=True)
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
                title="框选屏幕区域，识别二维码",
                sub_title="回车开始截图，框选后自动识别",
                icon=WoxImage.new_emoji("🔍"),
                actions=[
                    ResultAction(
                        name="开始截图识别",
                        icon=WoxImage.new_emoji("📸"),
                        action=self._action_scan,
                    )
                ],
            )
        ]
        for text in self._scan_texts:
            actions = [
                ResultAction(
                    name="复制识别结果",
                    icon=WoxImage.new_emoji("📋"),
                    context_data={"text": text},
                    action=self._action_copy_text,
                )
            ]
            if text.startswith(("http://", "https://")):
                actions.append(
                    ResultAction(
                        name="在浏览器中打开",
                        icon=WoxImage.new_emoji("🌐"),
                        context_data={"text": text},
                        action=self._action_open_url,
                    )
                )
            results.append(
                Result(
                    title=_short(text),
                    sub_title="识别结果",
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
                await self.api.notify(ctx, f"截图失败：{res.errmsg}")
            return
        try:
            texts = decode_qr_image(res.screenshot_path)
        except Exception as e:
            await self.api.log(ctx, LogLevel.ERROR, f"QR decode failed: {e}")
            await self.api.notify(ctx, f"识别失败：{e}")
            return
        if not texts:
            await self.api.notify(ctx, "未在截图中识别到二维码")
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
        await self.api.notify(ctx, f"已保存到桌面：{os.path.basename(dst)}")

    async def _action_open_url(self, ctx: Context, ac: ActionContext) -> None:
        url = (ac.context_data or {}).get("text", "")
        if url:
            webbrowser.open(url)


plugin = QRCodePlugin()

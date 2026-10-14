"""QRCode Wox plugin source package.

Intentionally import-free. Wox loads plugin.json's "Entry" (qrcode_main.py)
directly and never executes this file, so re-exporting plugin here would be
dead code that also pulls the runtime dependencies into any `import src`.
"""

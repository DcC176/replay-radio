"""APK 内的 Python 入口。

Java 层调用 start(appdir, root) 时：
- 设置 Android 环境标记与路径（serve.py 依赖这些全局变量在 import 时确定）
- HTTP 服务在 daemon 线程里启动，函数立即返回——
  否则 serve.main() 的 serve_forever() 会占住 Chaquopy 调用线程，WebView 拿不到控制权。
"""
import os
import sys
import threading

os.environ["REPLAYRADIO_ANDROID"] = "1"


def start(appdir, root):
    os.environ["REPLAYRADIO_APPDIR"] = appdir
    os.environ["REPLAYRADIO_ROOT"] = root
    sys.argv = ["serve.py", "--port", "8765", "--no-browser"]

    def run():
        try:
            import serve
            serve.main()
        except Exception as e:
            with open(os.path.join(appdir, "boot_error.txt"), "a", encoding="utf-8") as f:
                f.write("%s\n\n" % e)

    threading.Thread(target=run, daemon=True).start()
    return "ok"

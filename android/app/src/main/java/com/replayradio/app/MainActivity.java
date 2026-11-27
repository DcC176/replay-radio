package com.replayradio.app;

import android.app.Activity;
import android.os.Bundle;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import com.chaquo.python.Python;
import com.chaquo.python.PyObject;
import com.chaquo.python.android.AndroidPlatform;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;

public class MainActivity extends Activity {
    private WebView web;
    private File appDir;
    private File www;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        appDir = new File(getFilesDir(), "ReplayRadio");
        www = new File(appDir, "www");
        try {
            copyAssets("www_seed", www);   // 一次性释放网页种子到私有目录
        } catch (IOException e) {
            Toast.makeText(this, "网页资源释放失败：" + e.getMessage(), Toast.LENGTH_LONG).show();
        }

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        web.setWebViewClient(new WebViewClient());
        // 先显示一个带提示的占位页，后端就绪后再换成真正的界面
        web.loadDataWithBaseURL(null,
            "<div style='font:16px/1.8 system-ui,sans-serif;color:#c9c9d1;background:#08080a;" +
            "height:100%;display:flex;align-items:center;justify-content:center;margin:0'>" +
            "正在启动本地服务…</div>", "text/html", "utf-8", null);
        setContentView(web);

        // Chaquopy 在 Android 上必须先显式初始化，否则 Python.getInstance() 会抛
        // "Cannot use GenericPlatform on Android"。初始化放在后台线程，避免阻塞 UI。
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    if (!Python.isStarted()) {
                        Python.start(new AndroidPlatform(MainActivity.this));
                    }
                    Python py = Python.getInstance();
                    PyObject entry = py.getModule("android_entry");
                    entry.callAttr("start", appDir.getAbsolutePath(), www.getAbsolutePath());

                    // 后端线程刚起来，端口未必已监听。轮询就绪后再加载页面，
                    // 否则 WebView 会直接 ERR_CONNECTION_REFUSED。
                    if (waitForServer(8765, 30000)) {
                        web.post(new Runnable() {
                            @Override
                            public void run() {
                                // 一比一还原：直接加载原版 index.html
                                web.loadUrl("http://127.0.0.1:8765/");
                            }
                        });
                    } else {
                        showError("本地服务启动超时");
                    }
                } catch (final Exception e) {
                    showError("服务启动失败：" + e.getMessage());
                }
            }
        }, "backend-boot").start();
    }

    /** 轮询本机端口是否可连接，成功即返回 true。 */
    private boolean waitForServer(int port, int timeoutMs) {
        long deadline = System.currentTimeMillis() + timeoutMs;
        while (System.currentTimeMillis() < deadline) {
            Socket s = new Socket();
            try {
                s.connect(new InetSocketAddress("127.0.0.1", port), 500);
                return true;
            } catch (IOException e) {
                try { Thread.sleep(300); } catch (InterruptedException ie) { return false; }
            } finally {
                try { s.close(); } catch (IOException ignored) { }
            }
        }
        return false;
    }

    private void showError(final String msg) {
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                Toast.makeText(MainActivity.this, msg, Toast.LENGTH_LONG).show();
                web.loadDataWithBaseURL(null,
                    "<div style='font:16px/1.8 system-ui,sans-serif;color:#f2f2f4;background:#08080a;" +
                    "padding:40px'>" + msg + "</div>", "text/html", "utf-8", null);
            }
        });
    }

    /** 把 APK assets 下的 www_seed/ 目录整棵复制到目标目录（已存在则跳过）。 */
    private void copyAssets(String prefix, File target) throws IOException {
        String[] items = getAssets().list(prefix);
        if (items == null) return;
        if (!target.exists() && !target.mkdirs()) return;
        for (String item : items) {
            File out = new File(target, item);
            String child = prefix + "/" + item;
            String[] children = getAssets().list(child);
            if (children != null && children.length > 0) {
                if (!out.exists()) copyAssets(child, out);
            } else if (!out.exists()) {
                InputStream in = getAssets().open(child);
                OutputStream os = new FileOutputStream(out);
                byte[] buf = new byte[8192];
                int n;
                while ((n = in.read(buf)) > 0) os.write(buf, 0, n);
                in.close();
                os.close();
            }
        }
    }

    @Override
    public void onBackPressed() {
        super.onBackPressed();
    }
}

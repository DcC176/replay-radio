package com.replayradio.app;

import android.app.Activity;
import android.os.Bundle;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import com.chaquo.python.Python;
import com.chaquo.python.PyObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

public class MainActivity extends Activity {
    private static final String TAG = "ReplayRadio";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        File appDir = new File(getFilesDir(), "ReplayRadio");
        File www = new File(appDir, "www");
        try {
            copyAssets("www_seed", www);   // 一次性释放网页种子到私有目录
        } catch (IOException e) {
            Toast.makeText(this, "网页资源释放失败：" + e.getMessage(), Toast.LENGTH_LONG).show();
        }

        // 启动 Python 后端（在线程里跑 serve_forever，不阻塞主线程）
        try {
            Python py = Python.getInstance();
            PyObject entry = py.getModule("android_entry");
            entry.callAttr("start", appDir.getAbsolutePath(), www.getAbsolutePath());
        } catch (Exception e) {
            Toast.makeText(this, "服务启动失败：" + e.getMessage(), Toast.LENGTH_LONG).show();
        }

        WebView web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        web.setWebViewClient(new WebViewClient());
        setContentView(web);
        web.loadUrl("http://127.0.0.1:8765/?mobile=1");
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
        // 移动端避免误退出，交给 WebView 处理（当前页面无返回栈时再退出）
        super.onBackPressed();
    }
}

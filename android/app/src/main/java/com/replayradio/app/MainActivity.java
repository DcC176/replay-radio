package com.replayradio.app;

import android.app.Activity;
import android.os.Bundle;
import android.widget.TextView;
import com.chaquo.python.Python;
import com.chaquo.python.PyObject;

public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        TextView tv = new TextView(this);
        tv.setTextSize(20f);
        setContentView(tv);
        try {
            PyObject mod = Python.getInstance().getModule("hello");
            tv.setText("Chaquopy OK: " + mod.callAttr("greet").toString());
        } catch (Exception e) {
            tv.setText("Chaquopy FAIL: " + e.toString());
        }
    }
}

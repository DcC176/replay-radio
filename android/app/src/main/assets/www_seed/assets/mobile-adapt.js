/* 手机版适配层 JS（噼里啪啦）
   只做「手机/平板环境」增强：点击音效、轻触反馈、B 站快捷登录入口。
   不碰原版任何变量、函数与事件逻辑；登录复用原版弹窗（触发 #tb-login 的 click）。 */
(function () {
  "use strict";

  var actx = null;
  var coarse = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
  var isMobile = coarse || /Android|iPhone|iPad|Mobile/i.test(navigator.userAgent || "");

  function beep(kind) {
    if (!isMobile) return;
    try {
      if (!actx) actx = new (window.AudioContext || window.webkitAudioContext)();
      if (actx.state === "suspended") actx.resume();
      var o = actx.createOscillator(), g = actx.createGain(), t = actx.currentTime;
      o.connect(g); g.connect(actx.destination);
      var f = kind === "nav" ? 720 : kind === "play" ? 880 : 560;
      o.type = "triangle";
      o.frequency.setValueAtTime(f, t);
      o.frequency.exponentialRampToValueAtTime(f * 1.4, t + 0.07);
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.09, t + 0.008);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.13);
      o.start(t); o.stop(t + 0.15);
    } catch (e) { /* 音效失败不影响任何功能 */ }
  }

  if (coarse) {
    document.addEventListener("pointerdown", function (e) {
      var t = e.target;
      if (!t || !t.closest) return;
      var el = t.closest(".tab, .btn, button, .ob-card, a[href^='#/'], .ob-login-quick");
      if (!el) return;
      var kind = el.classList.contains("tab") ? "nav" :
                 /play|playbtn|toggle/i.test(el.id || "") ? "play" : "tap";
      beep(kind);
      try { navigator.vibrate && navigator.vibrate(10); } catch (e2) {}
    }, { passive: true });

    document.addEventListener("touchstart", function once() {
      if (actx && actx.state === "suspended") actx.resume();
    }, { passive: true, once: true });
  }

  /* ---------- B 站快捷登录入口 ----------
     首屏引导页阶段，原版 el 缓存尚未初始化、顶栏登录按钮没有监听器，
     所以这里用「原版登录弹窗 DOM + 后端 API + 页面已有的 QRCode 库」驱动扫码。
     进入主界面后原版监听器已绑定，直接触发 #tb-login 走原版逻辑。 */
  var qrTimerMobile = null;

  function openMobileLogin() {
    var panel = document.getElementById("login-panel");
    var anon = document.getElementById("lp-anon");
    var me = document.getElementById("lp-me");
    var qrBox = document.getElementById("login-qr");
    var status = document.getElementById("login-status");
    if (!panel || !qrBox || !status) return;
    panel.hidden = false;
    if (anon) anon.hidden = false;
    if (me) me.hidden = true;
    if (typeof QRCode === "undefined") { status.textContent = "二维码组件未就绪"; return; }
    status.textContent = "正在获取二维码…";
    qrBox.innerHTML = "";

    fetch("/api/login/qrcode").then(function (r) { return r.json(); }).then(function (d) {
      if (d.error) { status.textContent = "获取二维码失败：" + d.error; return; }
      qrBox.innerHTML = "";
      try {
        new QRCode(qrBox, { text: d.url, width: 152, height: 152, correctLevel: QRCode.CorrectLevel.M });
      } catch (e) { status.textContent = "二维码渲染失败：" + e.message; return; }
      status.textContent = "用 B 站手机 App 扫码登录";
      var key = d.key;
      if (qrTimerMobile) clearInterval(qrTimerMobile);
      qrTimerMobile = setInterval(function () {
        fetch("/api/login/poll?key=" + encodeURIComponent(key))
          .then(function (r) { return r.json(); }).then(function (s) {
            if (s.error) { status.textContent = s.error; return; }
            if (s.code === 0) {
              clearInterval(qrTimerMobile); qrTimerMobile = null;
              status.textContent = "登录成功，正在刷新…";
              setTimeout(function () { location.reload(); }, 700);
            } else if (s.code === 86090) {
              status.textContent = "已扫码，请在手机上点确认";
            } else if (s.code === 86038) {
              status.textContent = "二维码已失效，请重新打开";
              clearInterval(qrTimerMobile); qrTimerMobile = null;
            } else {
              status.textContent = "等待扫码…";
            }
          }).catch(function () { /* 网络抖动忽略，下次轮询继续 */ });
      }, 2000);
    }).catch(function (e) { status.textContent = "获取二维码出错：" + e.message; });
  }

  function injectLoginQuick() {
    var sub = document.getElementById("ob-sub");
    if (!sub || document.getElementById("ob-login-quick")) return;
    var btn = document.createElement("button");
    btn.id = "ob-login-quick";
    btn.className = "ob-login-quick";
    btn.type = "button";
    btn.innerHTML = "<span>扫码登录 B 站</span>";
    sub.parentNode.insertBefore(btn, sub.nextSibling);

    btn.addEventListener("click", function () {
      beep("tap");
      // 原版已进主界面：顶栏按钮有监听器，直接复用原版
      if (document.body.className && /(^|\s)view-/.test(document.body.className)) {
        var tb = document.getElementById("tb-login");
        if (tb) { tb.click(); return; }
      }
      openMobileLogin();
    });

    // 原版弹窗的关闭按钮在此场景下也应可用（原版未绑定时用适配层兜底）
    var x = document.getElementById("btn-login-close");
    if (x && !x.__mobileBound) {
      x.__mobileBound = true;
      x.addEventListener("click", function () {
        var p = document.getElementById("login-panel");
        if (p) p.hidden = true;
        if (qrTimerMobile) { clearInterval(qrTimerMobile); qrTimerMobile = null; }
      });
    }

    // 登录状态同步：读原版顶栏维护的登录态文字
    var nameEl = document.getElementById("tb-login-name");
    function sync() {
      if (!nameEl) return;
      var txt = (nameEl.textContent || "").trim();
      var logged = txt && txt !== "登录" && txt !== "登录 B 站";
      var span = btn.querySelector("span");
      if (span) span.textContent = logged ? ("已登录 · " + txt) : "扫码登录 B 站";
      btn.classList.toggle("is-logged", !!logged);
    }
    sync();
    if (nameEl && window.MutationObserver) {
      new MutationObserver(sync).observe(nameEl, { childList: true, subtree: true, characterData: true });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", injectLoginQuick);
  } else {
    injectLoginQuick();
  }
})();

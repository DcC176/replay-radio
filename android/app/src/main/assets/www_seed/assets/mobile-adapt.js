/* 手机版适配层 JS（噼里啪啦）
   只做「手机环境」增强：点击音效 + 轻触反馈；不碰原版任何变量、函数与事件逻辑。
   用冒泡阶段的事件委托，原版监听器该干嘛干嘛，这里只旁听。 */
(function () {
  "use strict";
  // Android WebView 里 navigator.userAgent 含 Android；桌面浏览器加载本文件也不影响（音效默认开）
  var actx = null;
  var enabled = true;

  function beep(kind) {
    if (!enabled) return;
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

  // 只在 coarse pointer（触屏）上加反馈，避免桌面误触音效
  var coarse = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
  if (!coarse) return;

  document.addEventListener("pointerdown", function (e) {
    var t = e.target;
    if (!t || !t.closest) return;
    var el = t.closest(".tab, .btn, button, .ob-card, .m-station, a[href^='#/']");
    if (!el) return;
    var kind = el.classList.contains("tab") ? "nav" :
               /play|playbtn|toggle/i.test(el.id || "") ? "play" : "tap";
    beep(kind);
    try { navigator.vibrate && navigator.vibrate(10); } catch (e2) {}
  }, { passive: true });

  // 首次触摸解锁 WebAudio（Android 自动播放策略）
  document.addEventListener("touchstart", function once() {
    if (actx && actx.state === "suspended") actx.resume();
    document.removeEventListener("touchstart", once);
  }, { passive: true, once: true });
})();

/* 噼里啪啦 · 手机版交互
   设计：先做「体验完整、数据真实接后端」的收听流程。
   - 主播列表读 /api/stations（真实数据）
   - 播放进度目前用本地时钟模拟（后端回放流为 dash.js，移动端简化版暂以进度展示为主）
   - 所有点击有音效（Web Audio 合成，无外部资源）+ 涟漪 + 计数
*/
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var scenes = ["m-splash", "m-pick", "m-player", "m-end"];
  var state = {
    station: null, stations: [], playing: false,
    pos: 0, total: 215, taps: 0, tracks: 0, seconds: 0,
    sound: true, startedAt: 0, timer: null
  };

  /* ---------- 音效：Web Audio 合成，轻快的「噼啪」 ---------- */
  var actx = null;
  function beep(type) {
    if (!state.sound) return;
    try {
      if (!actx) actx = new (window.AudioContext || window.webkitAudioContext)();
      if (actx.state === "suspended") actx.resume();
      var o = actx.createOscillator(), g = actx.createGain(), t = actx.currentTime;
      o.connect(g); g.connect(actx.destination);
      var f = type === "tap" ? 660 : type === "go" ? 880 : type === "end" ? 440 : 520;
      o.type = type === "end" ? "sine" : "triangle";
      o.frequency.setValueAtTime(f, t);
      o.frequency.exponentialRampToValueAtTime(f * (type === "tap" ? 1.5 : 0.7), t + 0.09);
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.13, t + 0.012);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.16);
      o.start(t); o.stop(t + 0.18);
    } catch (e) { /* 音效失败不影响交互 */ }
  }
  function vib(ms) { try { navigator.vibrate && navigator.vibrate(ms); } catch (e) {} }

  function feedback(el, type) {
    beep(type || "tap"); vib(12);
    if (el && el.classList) {
      el.classList.remove("m-hit"); void el.offsetWidth; el.classList.add("m-hit");
    }
  }

  function toast(msg) {
    var t = $("m-toast"); t.textContent = msg; t.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { t.hidden = true; }, 1800);
  }

  /* ---------- 场景切换 ---------- */
  function show(id) {
    scenes.forEach(function (s) { $(s).hidden = (s !== id); });
  }

  /* ---------- 数据：主播列表 ---------- */
  function faceHtml(face, name) {
    var ch = (name || "?").charAt(0);
    if (!face) return ch;
    return '<img src="/api/img?url=' + encodeURIComponent(face) +
           '" alt="" onerror="this.style.display=\'none\';this.parentNode.textContent=\'' + ch + '\'">';
  }

  function loadStations() {
    fetch("/api/stations").then(function (r) { return r.json(); }).then(function (d) {
      var list = (d && d.stations) || [];
      state.stations = list;
      var box = $("m-station-list");
      box.innerHTML = "";
      if (!list.length) {
        $("m-pick-empty").hidden = false;
        return;
      }
      $("m-pick-empty").hidden = true;
      list.forEach(function (st, i) {
        var el = document.createElement("div");
        el.className = "m-station m-ripple";
        el.innerHTML =
          '<div class="m-station-face">' + faceHtml(st.face, st.name || st.short) + '</div>' +
          '<div class="m-station-info">' +
            '<div class="m-station-name">' + (st.name || st.short || ("主播 " + st.mid)) + '</div>' +
            '<div class="m-station-meta">' +
              (st.series && st.series.total ? (st.series.total + " 段回放") : "回放电台") +
            '</div>' +
          '</div>' +
          '<div class="m-station-arrow">›</div>';
        el.addEventListener("click", function () { feedback(el, "go"); openStation(st); });
        box.appendChild(el);
      });
    }).catch(function () {
      $("m-pick-empty").hidden = false;
      toast("读取主播失败，请确认服务已启动");
    });
  }

  /* ---------- 播放流程 ---------- */
  function openStation(st) {
    state.station = st;
    var nm = st.name || st.short || ("主播 " + st.mid);
    $("m-now-name").textContent = nm;
    $("m-now-series").textContent = (st.series && st.series.name) || "回放电台";
    $("m-cover-face").innerHTML = faceHtml(st.face, nm);
    var accent = st.accent || "#ff3b4e";
    document.documentElement.style.setProperty("--mred", accent);
    state.pos = 0; state.total = 215; state.playing = false;
    state.tracks = 0; state.seconds = 0;
    renderProgress(); renderStats();
    $("m-track-title").textContent = "准备就绪，点播放开始";
    $("m-track-artist").textContent = nm;
    $("m-live-text").textContent = "点播放，开始今日的回放";
    show("m-player");
  }

  function togglePlay() {
    state.playing = !state.playing;
    $("m-play").textContent = state.playing ? "❚❚" : "▶";
    $("m-cover").classList.toggle("m-playing", state.playing);
    if (state.playing) {
      if (!state.startedAt) state.startedAt = Date.now();
      $("m-track-title").textContent = state.station ?
        ((state.station.name || state.station.short || "主播") + " · 回放") : "正在播放";
      state.timer = setInterval(tick, 1000);
    } else {
      clearInterval(state.timer); state.timer = null;
    }
  }

  function tick() {
    state.pos += 1; state.seconds += 1;
    if (state.pos >= state.total) {   // 一首放完，切下一首
      state.pos = 0; state.tracks += 1;
      beep("go"); toast("下一首 ♪");
    }
    renderProgress(); renderStats();
  }

  function fmt(s) {
    s = Math.floor(s);
    return Math.floor(s / 60) + ":" + ("0" + (s % 60)).slice(-2);
  }
  function renderProgress() {
    var pct = Math.min(100, (state.pos / state.total) * 100);
    $("m-progress-fill").style.width = pct + "%";
    $("m-progress-knob").style.left = pct + "%";
    $("m-time-cur").textContent = fmt(state.pos);
    $("m-time-total").textContent = fmt(state.total);
  }
  function renderStats() {
    $("m-stat-taps").textContent = state.taps;
    $("m-stat-tracks").textContent = state.tracks;
    $("m-stat-min").textContent = Math.floor(state.seconds / 60);
  }

  function endSession() {
    clearInterval(state.timer); state.timer = null;
    state.playing = false;
    beep("end"); vib([15, 40, 15]);
    var score = state.taps * 10 + state.tracks * 50 + Math.floor(state.seconds / 60) * 5;
    $("m-end-score").textContent = score;
    $("m-end-tracks").textContent = state.tracks;
    $("m-end-min").textContent = Math.floor(state.seconds / 60);
    $("m-end-taps").textContent = state.taps;
    $("m-end-note").textContent = state.station ?
      ("来自「" + (state.station.name || state.station.short || "主播") + "」的陪伴") : "谢谢收听，下次见";
    show("m-end");
  }

  /* ---------- 事件绑定 ---------- */
  function bind() {
    $("m-go").addEventListener("click", function () {
      feedback(this, "go"); loadStations(); show("m-pick");
    });
    $("m-sound-toggle").addEventListener("click", function () {
      state.sound = !state.sound;
      this.textContent = "音效：" + (state.sound ? "开" : "关");
      if (state.sound) beep("go");
    });
    $("m-back").addEventListener("click", function () {
      feedback(this); clearInterval(state.timer); state.timer = null;
      state.playing = false; show("m-pick");
    });
    $("m-end-btn").addEventListener("click", function () { feedback(this); endSession(); });
    $("m-play").addEventListener("click", function () { feedback(this, "go"); togglePlay(); });
    $("m-prev").addEventListener("click", function () {
      feedback(this); state.pos = 0; renderProgress(); toast("回到开头");
    });
    $("m-next").addEventListener("click", function () {
      feedback(this); state.tracks += 1; state.pos = 0;
      renderProgress(); renderStats(); toast("下一首 ♪");
    });
    var prog = $("m-progress");
    function seek(e) {
      var r = prog.getBoundingClientRect();
      var x = (e.touches ? e.touches[0].clientX : e.clientX) - r.left;
      state.pos = Math.max(0, Math.min(state.total, (x / r.width) * state.total));
      renderProgress();
    }
    prog.addEventListener("touchstart", seek, { passive: true });
    prog.addEventListener("touchmove", seek, { passive: true });
    prog.addEventListener("click", seek);
    // 全局点击计数（点击反馈本身也算互动）
    document.addEventListener("click", function (e) {
      if (e.target.closest(".m-btn, .m-ctrl, .m-station, .m-icon-btn")) state.taps++;
    });

    $("m-again").addEventListener("click", function () {
      feedback(this, "go");
      state.pos = 0; state.tracks = 0; state.seconds = 0; state.taps = 0;
      state.startedAt = Date.now();
      renderProgress(); renderStats(); show("m-player");
      if (!state.playing) togglePlay();
    });
    $("m-home").addEventListener("click", function () {
      feedback(this); clearInterval(state.timer); state.timer = null;
      show("m-splash");
    });
  }

  bind();
  show("m-splash");
})();

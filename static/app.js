/* ==========================================================================
   RISC-V AI 编译器挑战赛 · 评测平台
   极少量原生 JS：主题切换、05:00 结算倒计时、htmx 状态提示。
   页面的数据获取与局部刷新交给 htmx；这里不承载业务。
   ========================================================================== */
(function () {
  "use strict";

  /* ---------- 主题：localStorage 覆盖系统偏好 ---------- */
  var STORE_KEY = "riscv-contest-theme";
  var root = document.documentElement;

  function currentTheme() {
    return root.getAttribute("data-bs-theme") === "dark" ? "dark" : "light";
  }

  function paintToggle(btn) {
    if (!btn) return;
    var dark = currentTheme() === "dark";
    btn.setAttribute("aria-pressed", String(dark));
    btn.setAttribute("aria-label", dark ? "切换到浅色模式" : "切换到深色模式");
    var sun = btn.querySelector("[data-icon='sun']");
    var moon = btn.querySelector("[data-icon='moon']");
    if (sun) sun.hidden = dark;
    if (moon) moon.hidden = !dark;
  }

  function setTheme(mode, persist) {
    root.setAttribute("data-bs-theme", mode);
    if (persist) {
      try { localStorage.setItem(STORE_KEY, mode); } catch (e) { /* 隐私模式存不了，忽略 */ }
    }
    paintToggle(document.getElementById("themeToggle"));
  }

  var toggle = document.getElementById("themeToggle");
  paintToggle(toggle);
  if (toggle) {
    toggle.addEventListener("click", function () {
      setTheme(currentTheme() === "dark" ? "light" : "dark", true);
    });
  }

  // 用户没显式选过时，跟随系统变化
  try {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function (e) {
      var saved = null;
      try { saved = localStorage.getItem(STORE_KEY); } catch (err) { saved = null; }
      if (!saved) setTheme(e.matches ? "dark" : "light", false);
    });
  } catch (e) { /* 老浏览器无 addEventListener，忽略 */ }

  /* ---------- 距下一次 05:00（UTC+8）结算 ---------- */
  var DAY = 86400000;
  var UTC8 = 8 * 3600000;
  var RESET_HOUR = 5;

  function nextResetMs() {
    var shifted = Date.now() + UTC8;            // 把 UTC+8 当作"本地"来算
    var dayStart = Math.floor(shifted / DAY) * DAY;
    var reset = dayStart + RESET_HOUR * 3600000;
    if (reset <= shifted) reset += DAY;
    return reset - shifted;
  }

  function fmtRemain(ms) {
    var total = Math.floor(ms / 1000);
    var h = Math.floor(total / 3600);
    var m = Math.floor((total % 3600) / 60);
    if (h > 0) return h + " h " + m + " m";
    if (m > 0) return m + " m";
    return "< 1 m";
  }

  var countdowns = document.querySelectorAll("[data-countdown]");
  if (countdowns.length) {
    var tick = function () {
      var text = fmtRemain(nextResetMs());
      for (var i = 0; i < countdowns.length; i++) countdowns[i].textContent = text;
    };
    tick();
    setInterval(tick, 30000);
  }

  /* ---------- htmx：所有请求带上 CSRF token（Flask-WTF） ---------- */
  var csrfMeta = document.querySelector('meta[name="csrf-token"]');
  var csrfToken = csrfMeta ? csrfMeta.getAttribute("content") : "";
  document.body.addEventListener("htmx:configRequest", function (evt) {
    if (csrfToken) evt.detail.headers["X-CSRFToken"] = csrfToken;
  });

  /* ---------- htmx：允许 4xx 片段正常替换（表单错误要展示给用户） ---------- */
  var SWAP_ERROR_STATUS = [400, 403, 409, 413, 422, 429];
  document.body.addEventListener("htmx:beforeSwap", function (evt) {
    var status = evt.detail.xhr.status;
    if (SWAP_ERROR_STATUS.indexOf(status) !== -1) {
      evt.detail.shouldSwap = true;
      evt.detail.isError = false;
    }
  });

  /* ---------- htmx：真正失败（5xx/网络）时给出可操作提示，不静默 ---------- */
  document.body.addEventListener("htmx:responseError", function (evt) {
    var status = evt.detail.xhr && evt.detail.xhr.status;
    if (SWAP_ERROR_STATUS.indexOf(status) !== -1) return; // 已在片段里展示
    var target = evt.detail.target;
    if (!target) return;
    target.innerHTML =
      '<div class="notice notice-critical" role="alert">' +
      "<div><p class=\"mb-1\">操作没有完成，服务暂时不可用。请刷新页面重试；若持续失败，把当前 URL 和大致时间发给赛事群。</p>" +
      '<button class="btn btn-quiet btn-sm" type="button" onclick="location.reload()">重新加载</button></div>' +
      "</div>";
  });

  /* ---------- 提交成功后清空已选文件（避免重复提交同一补丁） ---------- */
  document.body.addEventListener("htmx:afterRequest", function (evt) {
    var form = evt.detail.elt;
    if (!form || form.tagName !== "FORM") return;
    if (evt.detail.successful && form.getAttribute("hx-post")) {
      try { form.reset(); } catch (e) { /* 忽略 */ }
    }
  });
})();

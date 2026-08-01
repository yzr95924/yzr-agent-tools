/* html-mcp management page.
 *
 * Auth: Bearer token stored in localStorage. User pastes once, persists
 * across page reloads (same browser).
 *
 * Talks to /api/* with `Authorization: Bearer <token>`. All errors
 * surface as a toast.
 */
(function () {
  "use strict";

  var TOKEN_KEY = "html_mcp_token";

  // --- DOM refs ----------------------------------------------------------
  var $input = document.getElementById("token-input");
  var $save = document.getElementById("token-save");
  var $status = document.getElementById("token-status");
  var $tbody = document.getElementById("file-tbody");
  var $empty = document.getElementById("empty-state");
  var $table = document.getElementById("file-table");
  var $previewSection = document.getElementById("preview-section");
  var $previewName = document.getElementById("preview-name");
  var $previewFrame = document.getElementById("preview-frame");
  var $toast = document.getElementById("toast");

  // --- helpers -----------------------------------------------------------

  function getToken() {
    return localStorage.getItem(TOKEN_KEY) || "";
  }

  function setToken(t) {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
    updateStatus();
  }

  function updateStatus() {
    var t = getToken();
    if (t) {
      $status.textContent = "已保存";
      $status.style.color = "var(--accent)";
    } else {
      $status.textContent = "未设置";
      $status.style.color = "var(--fg-dim)";
    }
  }

  function toast(msg, isError) {
    $toast.textContent = msg;
    $toast.style.borderColor = isError ? "var(--danger)" : "var(--border)";
    $toast.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { $toast.hidden = true; }, 2500);
  }

  function api(method, path) {
    var headers = { "Content-Type": "application/json" };
    var t = getToken();
    if (t) headers["Authorization"] = "Bearer " + t;
    return fetch(path, { method: method, headers: headers })
      .then(function (r) {
        if (r.status === 401) {
          toast("token 错误或缺失", true);
          throw new Error("unauthorized");
        }
        if (!r.ok) {
          return r.json().then(function (j) {
            toast(j.message || (method + " " + path + " 失败"), true);
            throw new Error(j.error || "http_" + r.status);
          });
        }
        return r.json();
      });
  }

  function fmtSize(n) {
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / (1024 * 1024)).toFixed(1) + " MB";
  }

  function fmtTime(unix) {
    var d = new Date(unix * 1000);
    var pad = function (n) { return n < 10 ? "0" + n : n; };
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate())
      + " " + pad(d.getHours()) + ":" + pad(d.getMinutes());
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
  }

  // --- actions ------------------------------------------------------------

  function loadFiles() {
    api("GET", "/api/files").then(function (data) {
      var files = data.files || [];
      $tbody.innerHTML = "";
      if (!files.length) {
        $empty.hidden = false;
        $table.hidden = true;
        return;
      }
      $empty.hidden = true;
      $table.hidden = false;
      files.forEach(function (f) {
        var tr = document.createElement("tr");

        var tdName = document.createElement("td");
        tdName.innerHTML = "<a href=\"#\" data-name=\"" + escapeHtml(f.name) + "\">"
          + escapeHtml(f.name) + "</a>";
        if (f.title) {
          tdName.appendChild(document.createTextNode(" "));
          var sub = document.createElement("span");
          sub.style.color = "var(--fg-dim)";
          sub.textContent = "(" + f.title + ")";
          tdName.appendChild(sub);
        }

        var tdSize = document.createElement("td");
        tdSize.textContent = fmtSize(f.size);

        var tdTime = document.createElement("td");
        tdTime.textContent = fmtTime(f.mtime);

        var tdUrl = document.createElement("td");
        tdUrl.style.fontFamily = "ui-monospace, monospace";
        tdUrl.style.fontSize = "12px";
        tdUrl.textContent = f.url;

        var tdAct = document.createElement("td");
        var copyBtn = document.createElement("button");
        copyBtn.textContent = "复制 URL";
        copyBtn.onclick = function () { copyUrl(f.url); };
        var delBtn = document.createElement("button");
        delBtn.textContent = "删除";
        delBtn.className = "danger";
        delBtn.onclick = function () { deleteFile(f.name); };
        tdAct.appendChild(copyBtn);
        tdAct.appendChild(delBtn);

        tr.appendChild(tdName);
        tr.appendChild(tdSize);
        tr.appendChild(tdTime);
        tr.appendChild(tdUrl);
        tr.appendChild(tdAct);
        $tbody.appendChild(tr);
      });
    }).catch(function () {
      // Error toast already shown by api().
    });
  }

  function preview(name) {
    $previewSection.hidden = false;
    $previewName.textContent = "(" + name + ")";
    $previewFrame.src = "/files/" + encodeURIComponent(name);
  }

  function copyUrl(url) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(
        function () { toast("已复制 URL 到剪贴板"); },
        function () { fallbackCopy(url); }
      );
    } else {
      fallbackCopy(url);
    }
  }

  function fallbackCopy(text) {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
      toast("已复制 URL");
    } catch (e) {
      toast("复制失败", true);
    }
    document.body.removeChild(ta);
  }

  function deleteFile(name) {
    if (!window.confirm("确定删除 " + name + "?")) return;
    api("DELETE", "/api/files/" + encodeURIComponent(name))
      .then(function () {
        toast("已删除 " + name);
        $previewSection.hidden = true;
        loadFiles();
      })
      .catch(function () { /* error toast already shown */ });
  }

  // --- wire up ------------------------------------------------------------

  $save.onclick = function () {
    var t = $input.value.trim();
    if (!t) {
      toast("token 不能为空", true);
      return;
    }
    setToken(t);
    $input.value = "";
    toast("token 已保存");
    loadFiles();
  };

  $input.onkeydown = function (e) {
    if (e.key === "Enter") $save.click();
  };

  // Click on filename → preview.
  $tbody.onclick = function (e) {
    var a = e.target.closest("a[data-name]");
    if (a) {
      e.preventDefault();
      preview(a.getAttribute("data-name"));
    }
  };

  // Initial: render whatever token state we have; attempt load (will 401
  // until a token is set).
  updateStatus();
  if (getToken()) loadFiles();
})();
/* html-mcp management page.
 *
 * Read-only: lists files via GET /api/files (no auth — public metadata for
 * a docroot nginx already serves unauthenticated at /files/*). No delete /
 * upload buttons — those go through agent MCP, see README.
 *
 * Talks to /api/files with no credential header. All errors surface as
 * a toast.
 */
(function () {
  "use strict";

  // --- DOM refs ----------------------------------------------------------
  var $tbody = document.getElementById("file-tbody");
  var $empty = document.getElementById("empty-state");
  var $table = document.getElementById("file-table");
  var $previewSection = document.getElementById("preview-section");
  var $previewName = document.getElementById("preview-name");
  var $previewFrame = document.getElementById("preview-frame");
  var $toast = document.getElementById("toast");

  // --- helpers -----------------------------------------------------------

  function toast(msg, isError) {
    $toast.textContent = msg;
    $toast.style.borderColor = isError ? "var(--danger)" : "var(--border)";
    $toast.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { $toast.hidden = true; }, 2500);
  }

  function api(method, path) {
    // No credential header — list is public. A 401 here would mean the
    // daemon is an older build that still requires a token; surface a
    // version-mismatch hint instead of asking for one (we deliberately
    // don't show a token input any more).
    var headers = { "Content-Type": "application/json" };
    return fetch(path, { method: method, headers: headers })
      .then(function (r) {
        if (r.status === 401) {
          toast("daemon 版本不匹配，请升级 html-mcp", true);
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
        tdUrl.appendChild(document.createTextNode(f.url + " "));
        var copyBtn = document.createElement("button");
        copyBtn.textContent = "复制";
        copyBtn.onclick = function () { copyUrl(f.url); };
        tdUrl.appendChild(copyBtn);

        tr.appendChild(tdName);
        tr.appendChild(tdSize);
        tr.appendChild(tdTime);
        tr.appendChild(tdUrl);
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

  // --- wire up ------------------------------------------------------------

  // Click on filename → preview.
  $tbody.onclick = function (e) {
    var a = e.target.closest("a[data-name]");
    if (a) {
      e.preventDefault();
      preview(a.getAttribute("data-name"));
    }
  };

  // Initial load — list is always public; just call.
  loadFiles();
})();

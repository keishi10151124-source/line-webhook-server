// Small helpers shared by every page.
(function () {
  // confirm before destructive forms
  document.querySelectorAll("form[data-confirm]").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      if (!window.confirm(f.dataset.confirm)) e.preventDefault();
    });
  });
  // stop double submits and show progress text
  document.querySelectorAll("button[data-busy-label]").forEach(function (b) {
    var form = b.form;
    if (!form) return;
    form.addEventListener("submit", function (e) {
      if (form.dataset.sent) { e.preventDefault(); return; }
      form.dataset.sent = "1";
      b.setAttribute("aria-disabled", "true");
      b.textContent = b.dataset.busyLabel;
    });
  });
  // poll a status URL and reload the page when it reaches a final state
  document.querySelectorAll("[data-poll]").forEach(function (el) {
    var url = el.dataset.poll;
    var until = (el.dataset.pollUntil || "").split(",");
    var timer = setInterval(function () {
      fetch(url, { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (d) {
        var s = d.status || d.analysis_status;
        if (until.indexOf(s) !== -1) { clearInterval(timer); window.location.reload(); }
      }).catch(function () {});
    }, 2500);
  });
})();

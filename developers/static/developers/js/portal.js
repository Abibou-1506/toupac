/* TOUPAC — Portail développeur. Vanilla, sans dépendance ni build. */
(function () {
  "use strict";

  // ─── Copie des blocs de code ───

  function copyBlock(button) {
    var block = button.closest(".code");
    var code = block && block.querySelector("code");
    if (!code) return;

    var done = function () {
      var original = button.textContent;
      button.textContent = "Copié";
      button.classList.add("is-done");
      setTimeout(function () {
        button.textContent = original;
        button.classList.remove("is-done");
      }, 1600);
    };

    // navigator.clipboard exige un contexte sécurisé : en HTTP nu (serveur de
    // dev) il est absent, d'où le repli sur la sélection + execCommand.
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(code.textContent).then(done);
      return;
    }

    var selection = window.getSelection();
    var range = document.createRange();
    range.selectNodeContents(code);
    selection.removeAllRanges();
    selection.addRange(range);
    try {
      document.execCommand("copy");
      done();
    } finally {
      selection.removeAllRanges();
    }
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest(".copy");
    if (button) copyBlock(button);
  });

  // ─── Onglets de langage ───

  document.querySelectorAll("[data-tabs]").forEach(function (group) {
    group.addEventListener("click", function (event) {
      var tab = event.target.closest(".tab");
      if (!tab) return;

      var name = tab.dataset.tab;
      group.querySelectorAll(".tab").forEach(function (other) {
        other.classList.toggle("is-active", other === tab);
      });
      group.querySelectorAll(".tabpanel").forEach(function (panel) {
        panel.classList.toggle("is-active", panel.dataset.panel === name);
      });
    });
  });

  // ─── Surlignage de la section courante dans le sommaire ───

  var links = Array.prototype.slice.call(
    document.querySelectorAll(".sidebar a[href^='#']")
  );
  var sections = links
    .map(function (link) { return document.querySelector(link.getAttribute("href")); })
    .filter(Boolean);

  if (!sections.length || !("IntersectionObserver" in window)) return;

  var visible = new Set();
  var observer = new IntersectionObserver(
    function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) visible.add(entry.target.id);
        else visible.delete(entry.target.id);
      });

      // La première section visible dans l'ordre du document, pour éviter que
      // le surlignage saute quand plusieurs sections courtes coexistent.
      var current = sections.find(function (section) { return visible.has(section.id); });
      links.forEach(function (link) {
        link.classList.toggle(
          "is-current",
          current !== undefined && link.getAttribute("href") === "#" + current.id
        );
      });
    },
    { rootMargin: "-70px 0px -70% 0px" }
  );

  sections.forEach(function (section) { observer.observe(section); });
})();

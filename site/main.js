/* ============================================================
   Leike landing — Lenis smooth scroll + GSAP animations
   Degrades gracefully if a CDN fails or reduced-motion is set.
   ============================================================ */
(function () {
  "use strict";

  window.__leikeReady = true; // tells the head-script watchdog init ran

  var html = document.documentElement;
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var hasGSAP = typeof window.gsap !== "undefined";

  /* ---- inject minimal line icons into feature cards ---- */
  var ICONS = {
    crop: '<path d="M6 2v14a2 2 0 0 0 2 2h14"/><path d="M2 6h14a2 2 0 0 1 2 2v14"/>',
    trim: '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><line x1="20" y1="4" x2="8.12" y2="15.88"/><line x1="14.47" y1="14.48" x2="20" y2="20"/><line x1="8.12" y1="8.12" x2="12" y2="12"/>',
    format: '<rect x="3" y="4" width="18" height="16" rx="2"/><line x1="7" y1="4" x2="7" y2="20"/><line x1="17" y1="4" x2="17" y2="20"/><line x1="3" y1="12" x2="21" y2="12"/>',
    gpu: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    transform: '<polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>',
    adjust: '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>',
    overlay: '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
    size: '<polyline points="4 14 10 14 10 20"/><polyline points="20 10 14 10 14 4"/><line x1="14" y1="10" x2="21" y2="3"/><line x1="3" y1="21" x2="10" y2="14"/>',
    stabilize: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><polyline points="9 12 11 14 15 10"/>',
    grab: '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>',
    audio: '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>',
    local: '<rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>',
    play: '<polygon points="6 3 20 12 6 21 6 3"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    combine: '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>'
  };
  var SVG_OPEN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">';
  Array.prototype.forEach.call(document.querySelectorAll(".fi[data-icon]"), function (el) {
    var k = el.getAttribute("data-icon");
    if (ICONS[k]) el.innerHTML = SVG_OPEN + ICONS[k] + "</svg>";
  });

  /* ---- live version line + changelog modal (works with or without GSAP) ---- */
  initChangelog();

  /* ---- split the hero lede into masked words ---- */
  var lede = document.querySelector(".lede[data-split]");
  if (lede) {
    var words = lede.textContent.split(" ");
    lede.innerHTML = words
      .map(function (w) {
        return '<span class="word-mask" style="display:inline-block;overflow:hidden;vertical-align:top">' +
               '<span class="word">' + w + "</span></span>";
      })
      .join(" ");
  }

  /* ---- smooth anchor scrolling helper (set after Lenis init) ---- */
  var scrollToTarget = function (sel) {
    var node = document.querySelector(sel);
    if (node) node.scrollIntoView({ behavior: reduce ? "auto" : "smooth" });
  };

  /* ============================================================
     Reduced motion / no-GSAP: show everything, wire anchors, done.
     ============================================================ */
  if (reduce || !hasGSAP) {
    html.classList.add("no-anim");
    bindAnchors();
    return;
  }

  html.classList.add("gsap-ready"); // CSS hides hero/reveal items until animated

  var gsap = window.gsap;
  var hasST = typeof window.ScrollTrigger !== "undefined";
  if (hasST) gsap.registerPlugin(window.ScrollTrigger);

  /* ---- Lenis smooth scroll, synced to GSAP ticker + ScrollTrigger ---- */
  var lenis = null;
  if (typeof window.Lenis !== "undefined") {
    lenis = new window.Lenis({ lerp: 0.1, wheelMultiplier: 1, smoothWheel: true });
    window.lenis = lenis; // expose for programmatic scroll
    if (hasST) lenis.on("scroll", window.ScrollTrigger.update);
    gsap.ticker.add(function (t) { lenis.raf(t * 1000); });
    gsap.ticker.lagSmoothing(0);
    scrollToTarget = function (sel) { lenis.scrollTo(sel, { offset: 0 }); };
  }
  bindAnchors();

  /* ============================================================
     HERO intro timeline
     ============================================================ */
  gsap.set(".wordmark", { opacity: 1 });
  gsap.set(".wm-left", { xPercent: -100, opacity: 0 });
  gsap.set(".wm-right", { xPercent: 100, opacity: 0 });
  gsap.set([".eyebrow", ".sub", ".hero-cta", ".marquee", ".scroll-cue"], { opacity: 0, y: 26 });
  gsap.set(".lede .word", { yPercent: 115 });
  gsap.set(".lede", { opacity: 1 });

  var hero = gsap.timeline({ defaults: { ease: "power3.out" }, delay: 0.15 });
  hero
    .to(".eyebrow", { opacity: 1, y: 0, duration: 0.7 })
    // the cream "LEI" slides in from the left, the gold "KE" from the right,
    // overshooting a little as they meet (a bounce at the seam) while fading up
    // from transparent.
    .to(".wm-left", { xPercent: 0, duration: 1.2, ease: "back.out(0.9)" }, "-=0.3")
    .to(".wm-right", { xPercent: 0, duration: 1.2, ease: "back.out(0.9)" }, "<")
    .to([".wm-left", ".wm-right"], { opacity: 1, duration: 1.0, ease: "power2.out" }, "<")
    .to(".lede .word", { yPercent: 0, duration: 0.9, stagger: 0.06, ease: "power4.out" }, "-=0.8")
    .to(".sub", { opacity: 1, y: 0, duration: 0.7 }, "-=0.55")
    .to(".hero-cta", { opacity: 1, y: 0, duration: 0.7 }, "-=0.5")
    .to(".marquee", { opacity: 1, y: 0, duration: 0.8 }, "-=0.4")
    .to(".scroll-cue", { opacity: 1, y: 0, duration: 0.6 }, "-=0.5");

  // floating scroll-cue dot
  gsap.to(".scroll-cue span", { y: 10, repeat: -1, yoyo: true, duration: 0.9, ease: "sine.inOut" });

  // verb marquee — clone the set enough times to overflow the viewport, then
  // loop by exactly one set's width so it scrolls seamlessly (no gap, any size).
  (function initMarquee() {
    var track = document.querySelector(".marquee-track");
    var firstSet = track && track.querySelector(".marquee-set");
    if (!track || !firstSet) return;
    var SPEED = 60; // px per second
    var tween = null;
    function build() {
      var clones = track.querySelectorAll(".marquee-set");
      for (var i = clones.length - 1; i >= 1; i--) clones[i].remove();
      var setW = firstSet.getBoundingClientRect().width;
      if (!setW) return;
      var view = (track.parentElement || track).getBoundingClientRect().width || 1920;
      var need = Math.ceil(view / setW) + 1;
      for (var j = 1; j < need; j++) track.appendChild(firstSet.cloneNode(true));
      if (tween) tween.kill();
      gsap.set(track, { x: 0 });
      tween = gsap.to(track, { x: -setW, duration: setW / SPEED, ease: "none", repeat: -1 });
    }
    build();
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(build);
    var rt;
    window.addEventListener("resize", function () {
      clearTimeout(rt);
      rt = setTimeout(build, 200);
    });
  })();

  /* ============================================================
     ScrollTrigger-driven effects
     ============================================================ */
  if (hasST) {
    var ST = window.ScrollTrigger;

    // nav background on scroll
    ST.create({
      start: "top -60",
      end: 99999,
      onUpdate: function (self) {
        document.getElementById("nav").classList.toggle("scrolled", self.scroll() > 60);
      }
    });

    // top progress bar
    gsap.to(".scroll-progress span", {
      scaleX: 1, ease: "none",
      scrollTrigger: { start: 0, end: "max", scrub: 0.3 }
    });

    // parallax background glows
    gsap.utils.toArray(".glow").forEach(function (g, i) {
      gsap.to(g, {
        yPercent: (i % 2 === 0 ? -1 : 1) * (18 + i * 8), ease: "none",
        scrollTrigger: { start: 0, end: "max", scrub: 1 }
      });
    });

    // showcase screenshot — tilt-to-flat scrub reveal
    gsap.fromTo("#shotFrame",
      { rotateX: 38, y: 96, scale: 0.84, opacity: 0.35 },
      {
        rotateX: 0, y: 0, scale: 1, opacity: 1, ease: "none",
        scrollTrigger: { trigger: "#shotStage", start: "top 90%", end: "top 30%", scrub: 1 }
      });

    // generic reveals (section titles, ledes, kickers, download cards)
    gsap.utils.toArray("[data-reveal]").forEach(function (el) {
      gsap.fromTo(el, { opacity: 0, y: 40 },
        {
          opacity: 1, y: 0, duration: 0.9, ease: "power3.out",
          scrollTrigger: { trigger: el, start: "top 88%" }
        });
    });

    // feature cards — staggered batch reveal
    ST.batch("[data-feature]", {
      start: "top 90%",
      onEnter: function (els) {
        gsap.fromTo(els, { opacity: 0, y: 48, scale: 0.96 },
          { opacity: 1, y: 0, scale: 1, duration: 0.7, ease: "power3.out", stagger: 0.08, overwrite: true });
      }
    });

    // refresh once images/fonts settle
    window.addEventListener("load", function () { ST.refresh(); });
  }

  /* ============================================================
     Magnetic buttons (pointer-following nudge)
     ============================================================ */
  if (window.matchMedia("(pointer: fine)").matches) {
    gsap.utils.toArray(".magnetic").forEach(function (btn) {
      var xTo = gsap.quickTo(btn, "x", { duration: 0.4, ease: "power3" });
      var yTo = gsap.quickTo(btn, "y", { duration: 0.4, ease: "power3" });
      btn.addEventListener("mousemove", function (e) {
        var r = btn.getBoundingClientRect();
        xTo((e.clientX - (r.left + r.width / 2)) * 0.3);
        yTo((e.clientY - (r.top + r.height / 2)) * 0.4);
      });
      btn.addEventListener("mouseleave", function () { xTo(0); yTo(0); });
    });
  }

  /* ---- helpers ---- */
  function bindAnchors() {
    Array.prototype.forEach.call(document.querySelectorAll('a[href^="#"]'), function (a) {
      a.addEventListener("click", function (e) {
        var id = a.getAttribute("href");
        if (id.length > 1 && document.querySelector(id)) {
          e.preventDefault();
          scrollToTarget(id);
        }
      });
    });
  }

  /* ---- changelog modal + live version line ---- */
  function initChangelog() {
    var REPO = "Ville-Mattila/Leike";
    var API = "https://api.github.com/repos/" + REPO;
    var modal = document.getElementById("changelog");
    var body = document.getElementById("changelogBody");
    var verTag = document.getElementById("dlVersion");
    if (!modal) return;
    var loaded = false;
    var backdrop = modal.querySelector(".modal-backdrop");
    var panel = modal.querySelector(".modal-panel");

    fetch(API + "/releases/latest")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (rel) {
        if (rel && verTag) {
          verTag.textContent = rel.tag_name + " · released " + fmtDate(rel.published_at);
        }
      }).catch(function () {});

    function fmtDate(iso) {
      try {
        return new Date(iso).toLocaleDateString("en-US",
          { year: "numeric", month: "short", day: "numeric" });
      } catch (e) { return ""; }
    }

    function fail() {
      body.innerHTML = '<p class="modal-loading">Couldn\'t load releases — ' +
        '<a href="https://github.com/' + REPO + '/releases" target="_blank" rel="noopener">view on GitHub ↗</a></p>';
    }

    function load() {
      fetch(API + "/releases?per_page=20")
        .then(function (r) { return r.ok ? r.json() : []; })
        .then(function (rels) {
          if (!rels || !rels.length) { fail(); return; }
          body.innerHTML = rels.map(function (rel) {
            return '<div class="cl-release"><div class="cl-head">' +
              '<span class="cl-tag">' + esc(rel.tag_name) + '</span>' +
              '<span class="cl-date">' + fmtDate(rel.published_at) + '</span></div>' +
              mdToHtml(whatsNew(rel.body || "")) + '</div>';
          }).join("");
        }).catch(fail);
    }

    function open(e) {
      if (e) e.preventDefault();
      modal.classList.add("open");
      modal.setAttribute("aria-hidden", "false");
      if (window.lenis) window.lenis.stop();
      document.addEventListener("keydown", onKey);
      if (window.gsap) {
        window.gsap.fromTo(backdrop, { opacity: 0 }, { opacity: 1, duration: 0.3 });
        window.gsap.fromTo(panel, { opacity: 0, y: 24, scale: 0.98 },
          { opacity: 1, y: 0, scale: 1, duration: 0.4, ease: "power3.out" });
      } else { backdrop.style.opacity = 1; panel.style.opacity = 1; }
      if (!loaded) { loaded = true; load(); }
    }

    function close() {
      document.removeEventListener("keydown", onKey);
      if (window.lenis) window.lenis.start();
      var done = function () {
        modal.classList.remove("open");
        modal.setAttribute("aria-hidden", "true");
      };
      if (window.gsap) {
        window.gsap.to(panel, { opacity: 0, y: 16, duration: 0.22, ease: "power2.in" });
        window.gsap.to(backdrop, { opacity: 0, duration: 0.22, onComplete: done });
      } else { done(); }
    }

    function onKey(e) { if (e.key === "Escape") close(); }

    ["navChangelog", "dlChangelog"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.addEventListener("click", open);
    });
    Array.prototype.forEach.call(modal.querySelectorAll("[data-close]"),
      function (el) { el.addEventListener("click", close); });
  }

  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  /* Keep only the "What's new" changes from a release body — drop the tagline,
     Downloads, License, and any other boilerplate sections. */
  function whatsNew(md) {
    var s = (md || "").replace(/\r/g, "").trim();
    // cut the Downloads / License / Get-Leike sections and everything after
    s = s.split(/\n#{1,4}\s+(?:downloads|license|get\b|install)/i)[0];
    // prefer the content under a "What's new" heading
    var m = s.match(/#{1,4}\s+what['’]?s new[^\n]*\n([\s\S]*)/i);
    if (m) s = m[1];
    else s = s.replace(/^\s*\*\*Leike\*\*[^\n]*\n+/i, "");   // strip tagline
    return s.trim() || "_No notable changes._";
  }

  /* Minimal markdown → HTML for release notes (headings, lists, bold, code,
     links). Input is escaped first. */
  function mdToHtml(md) {
    var h = esc(md).replace(/\r/g, "");
    h = h.replace(/`([^`]+)`/g, "<code>$1</code>");
    h = h.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    h = h.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
    h = h.replace(/\[([^\]]+)\]\(([^)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>');
    var out = [], inList = false;
    h.split("\n").forEach(function (line) {
      var hm = line.match(/^(#{1,4})\s+(.*)$/);
      if (hm) {
        if (inList) { out.push("</ul>"); inList = false; }
        var lvl = Math.min(hm[1].length + 1, 5);
        out.push("<h" + lvl + ">" + hm[2] + "</h" + lvl + ">");
      } else if (/^\s*[-*]\s+/.test(line)) {
        if (!inList) { out.push("<ul>"); inList = true; }
        out.push("<li>" + line.replace(/^\s*[-*]\s+/, "") + "</li>");
      } else if (line.trim() === "") {
        if (inList) { out.push("</ul>"); inList = false; }
      } else {
        if (inList) { out.push("</ul>"); inList = false; }
        out.push("<p>" + line + "</p>");
      }
    });
    if (inList) out.push("</ul>");
    return out.join("\n");
  }
})();

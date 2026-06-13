/* ============================================================
   Leike landing — Lenis smooth scroll + GSAP animations
   Degrades gracefully if a CDN fails or reduced-motion is set.
   ============================================================ */
(function () {
  "use strict";

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
    local: '<rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>'
  };
  var SVG_OPEN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">';
  Array.prototype.forEach.call(document.querySelectorAll(".fi[data-icon]"), function (el) {
    var k = el.getAttribute("data-icon");
    if (ICONS[k]) el.innerHTML = SVG_OPEN + ICONS[k] + "</svg>";
  });

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
  gsap.set(".wordmark", { clipPath: "inset(0 100% 0 0)", opacity: 1, scale: 0.96 });
  gsap.set([".eyebrow", ".sub", ".hero-cta", ".marquee", ".scroll-cue"], { opacity: 0, y: 26 });
  gsap.set(".lede .word", { yPercent: 115 });
  gsap.set(".lede", { opacity: 1 });

  var hero = gsap.timeline({ defaults: { ease: "power3.out" }, delay: 0.15 });
  hero
    .to(".eyebrow", { opacity: 1, y: 0, duration: 0.7 })
    .to(".wordmark", { clipPath: "inset(0 0% 0 0)", scale: 1, duration: 1.15, ease: "power4.out" }, "-=0.35")
    .to(".lede .word", { yPercent: 0, duration: 0.9, stagger: 0.06, ease: "power4.out" }, "-=0.7")
    .to(".sub", { opacity: 1, y: 0, duration: 0.7 }, "-=0.55")
    .to(".hero-cta", { opacity: 1, y: 0, duration: 0.7 }, "-=0.5")
    .to(".marquee", { opacity: 1, y: 0, duration: 0.8 }, "-=0.4")
    .to(".scroll-cue", { opacity: 1, y: 0, duration: 0.6 }, "-=0.5");

  // floating scroll-cue dot
  gsap.to(".scroll-cue span", { y: 10, repeat: -1, yoyo: true, duration: 0.9, ease: "sine.inOut" });

  // verb marquee — seamless loop (content is duplicated in markup)
  gsap.to(".marquee-track", { xPercent: -50, repeat: -1, duration: 26, ease: "none" });

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
      { rotateX: 24, y: 70, scale: 0.88, opacity: 0.55 },
      {
        rotateX: 0, y: 0, scale: 1, opacity: 1, ease: "none",
        scrollTrigger: { trigger: "#shotStage", start: "top 85%", end: "top 35%", scrub: 1 }
      });
    // gentle continued parallax on the image after it settles
    gsap.to("#shotFrame img", {
      yPercent: -6, ease: "none",
      scrollTrigger: { trigger: "#shotStage", start: "top 35%", end: "bottom top", scrub: 1 }
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
})();

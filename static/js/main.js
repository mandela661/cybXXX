/* ===================== CyberX — main.js ===================== */
document.addEventListener("DOMContentLoaded", () => {

  /* ---------- загрузчик ---------- */
  const loader = document.getElementById("loader");
  if (loader) {
    window.addEventListener("load", () => setTimeout(() => loader.classList.add("hide"), 350));
    setTimeout(() => loader.classList.add("hide"), 1600); // подстраховка
  }

  /* ---------- кастомный курсор ---------- */
  const dot = document.querySelector(".cursor-dot");
  const ring = document.querySelector(".cursor-ring");
  if (dot && ring && window.matchMedia("(min-width:901px)").matches) {
    let rx = 0, ry = 0, mx = 0, my = 0;
    window.addEventListener("mousemove", e => {
      mx = e.clientX; my = e.clientY;
      dot.style.transform = `translate(${mx}px,${my}px) translate(-50%,-50%)`;
    });
    const loop = () => {
      rx += (mx - rx) * 0.18; ry += (my - ry) * 0.18;
      ring.style.transform = `translate(${rx}px,${ry}px) translate(-50%,-50%)`;
      requestAnimationFrame(loop);
    };
    loop();
    document.querySelectorAll("a,button,.chip,.card,input,select,textarea,summary")
      .forEach(el => {
        el.addEventListener("mouseenter", () => ring.classList.add("hover"));
        el.addEventListener("mouseleave", () => ring.classList.remove("hover"));
      });
  }

  /* ---------- шапка при скролле ---------- */
  const header = document.querySelector(".header");
  if (header) {
    const onScroll = () => header.classList.toggle("scrolled", window.scrollY > 20);
    onScroll(); window.addEventListener("scroll", onScroll);
  }

  /* ---------- мобильное меню ---------- */
  const burger = document.querySelector(".burger");
  const links = document.querySelector(".nav-links");
  if (burger && links) {
    burger.addEventListener("click", () => links.classList.toggle("open"));
    links.querySelectorAll("a").forEach(a => a.addEventListener("click", () => links.classList.remove("open")));
  }

  /* ---------- вкладки авторизации ---------- */
  document.querySelectorAll(".auth-tabs button").forEach(btn => {
    btn.addEventListener("click", () => switchAuthTab(btn.dataset.tab));
  });
  function switchAuthTab(name) {
    document.querySelectorAll(".auth-tabs button").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
    document.querySelectorAll(".auth-form").forEach(f => f.classList.toggle("active", f.dataset.form === name));
  }
  const openTab = document.body.dataset.openTab;
  if (openTab) switchAuthTab(openTab);

  /* ---------- вкладки админки ---------- */
  document.querySelectorAll(".admin-side a[data-tab]").forEach(a => {
    a.addEventListener("click", e => {
      e.preventDefault();
      const t = a.dataset.tab;
      document.querySelectorAll(".admin-side a").forEach(x => x.classList.toggle("active", x === a));
      document.querySelectorAll(".admin-panel").forEach(p => p.classList.toggle("active", p.dataset.panel === t));
      history.replaceState(null, "", "?tab=" + t);
    });
  });

  /* ---------- scroll-reveal ---------- */
  const io = new IntersectionObserver(entries => {
    entries.forEach(en => { if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); } });
  }, { threshold: 0.12 });
  document.querySelectorAll(".reveal").forEach(el => io.observe(el));

  /* ---------- счётчики ---------- */
  const counters = document.querySelectorAll("[data-count]");
  if (counters.length) {
    const cio = new IntersectionObserver(entries => {
      entries.forEach(en => {
        if (!en.isIntersecting) return;
        const el = en.target, target = parseInt(el.dataset.count, 10);
        if (isNaN(target)) { cio.unobserve(el); return; }
        let cur = 0; const step = Math.max(1, Math.ceil(target / 60));
        const tick = () => { cur += step; if (cur >= target) cur = target;
          el.textContent = cur.toLocaleString("ru-RU"); if (cur < target) requestAnimationFrame(tick); };
        tick(); cio.unobserve(el);
      });
    }, { threshold: 0.5 });
    counters.forEach(c => cio.observe(c));
  }

  /* ---------- универсальные фильтры (игры / периферия) ---------- */
  document.querySelectorAll("[data-filterable]").forEach(initFilter);
  function initFilter(scope) {
    const chips = scope.querySelectorAll(".chip");
    const search = scope.querySelector("[data-search]");
    const items = [...scope.querySelectorAll("[data-tags]")];
    const empty = scope.querySelector(".empty-note");
    let active = "all";
    const apply = () => {
      const q = (search?.value || "").trim().toLowerCase();
      let shown = 0;
      items.forEach(it => {
        const tags = it.dataset.tags.toLowerCase();
        const name = (it.dataset.name || "").toLowerCase();
        const okCat = active === "all" || tags.split("|").includes(active.toLowerCase());
        const okQ = !q || name.includes(q) || tags.includes(q);
        const ok = okCat && okQ;
        it.style.display = ok ? "" : "none";
        if (ok) shown++;
      });
      if (empty) empty.style.display = shown ? "none" : "block";
    };
    chips.forEach(c => c.addEventListener("click", () => {
      chips.forEach(x => x.classList.toggle("active", x === c));
      active = c.dataset.filter; apply();
    }));
    search?.addEventListener("input", apply);
    apply();
  }

  /* ---------- виджет бронирования ---------- */
  document.querySelectorAll("[data-booking]").forEach(card => {
    const price = parseInt(card.dataset.price, 10) || 0;
    const panel = card.querySelector(".booking");
    const trigger = card.querySelector(".booking-trigger");
    const input = card.querySelector(".hours-input");
    const totalEl = card.querySelector(".total-val");
    const lbl = card.querySelector(".hours-lbl");
    const dec = card.querySelector(".step-dec");
    const inc = card.querySelector(".step-inc");

    const hoursWord = h => {
      const n = h % 100, n1 = h % 10;
      if (n > 10 && n < 20) return "часов";
      if (n1 === 1) return "час";
      if (n1 >= 2 && n1 <= 4) return "часа";
      return "часов";
    };
    const render = () => {
      let h = Math.min(24, Math.max(1, parseInt(input.value, 10) || 1));
      input.value = h;
      if (totalEl) totalEl.textContent = (price * h).toLocaleString("ru-RU") + " ₽";
      if (lbl) lbl.textContent = h + " " + hoursWord(h);
    };
    trigger?.addEventListener("click", () => {
      panel.classList.toggle("open");
      trigger.querySelector("span").textContent = panel.classList.contains("open") ? "Свернуть" : "Забронировать";
    });
    dec?.addEventListener("click", () => { input.value = (parseInt(input.value, 10) || 1) - 1; render(); });
    inc?.addEventListener("click", () => { input.value = (parseInt(input.value, 10) || 1) + 1; render(); });
    input?.addEventListener("input", render);
    render();
  });

  /* ---------- авто-скрытие flash ---------- */
  document.querySelectorAll(".flash").forEach(f => {
    setTimeout(() => { f.style.opacity = "0"; f.style.transform = "translateX(20px)"; }, 4200);
    setTimeout(() => f.remove(), 4800);
  });

  /* ---------- звёзды-рейтинг в форме отзыва ---------- */
  const ratingInput = document.querySelector("[data-rating-input]");
  if (ratingInput) {
    const stars = ratingInput.querySelectorAll("i");
    const hidden = ratingInput.parentElement.querySelector("input[name='rating']");
    const paint = v => stars.forEach((s, i) => s.classList.toggle("off", i >= v));
    stars.forEach((s, i) => {
      s.addEventListener("mouseenter", () => paint(i + 1));
      s.addEventListener("click", () => { hidden.value = i + 1; paint(i + 1); ratingInput.dataset.val = i + 1; });
    });
    ratingInput.addEventListener("mouseleave", () => paint(parseInt(ratingInput.dataset.val || 5, 10)));
    paint(5);
  }
});


// ===== CyberX update: flip cards and game profile cards =====
(() => {
  document.querySelectorAll('.flip-card').forEach((card) => {
    card.addEventListener('click', () => card.classList.toggle('is-flipped'));
    card.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        card.classList.toggle('is-flipped');
      }
    });
  });

  document.querySelectorAll('.game-stat-card').forEach((card) => {
    card.addEventListener('click', () => {
      const isOpen = card.classList.toggle('is-open');
      card.setAttribute('aria-expanded', String(isOpen));
    });
  });
})();


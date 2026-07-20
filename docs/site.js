(() => {
  "use strict";

  const root = document.documentElement;
  const languageButton = document.getElementById("language-toggle");
  const themeButton = document.getElementById("theme-toggle");
  const menuButton = document.querySelector(".menu-toggle");
  const menu = document.getElementById("primary-menu");
  const toast = document.getElementById("toast");
  const titles = {
    zh: "vivarium｜可验证、可恢复的比较基因组分析工作流",
    en: "vivarium | Verifiable and recoverable comparative-genomics workflows",
  };

  let language = localStorage.getItem("vivarium-language");
  if (language !== "zh" && language !== "en") {
    language = navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en";
  }

  function applyLanguage(nextLanguage) {
    language = nextLanguage;
    root.lang = language === "zh" ? "zh-CN" : "en";
    document.title = titles[language];

    document.querySelectorAll("[data-zh][data-en]").forEach((element) => {
      element.textContent = element.dataset[language];
    });
    document.querySelectorAll("[data-alt-zh][data-alt-en]").forEach((image) => {
      image.alt = language === "zh" ? image.dataset.altZh : image.dataset.altEn;
    });

    if (languageButton) {
      languageButton.textContent = language === "zh" ? "EN" : "中文";
      languageButton.setAttribute(
        "aria-label",
        language === "zh" ? "Switch to English" : "切换到中文",
      );
    }
    localStorage.setItem("vivarium-language", language);
  }

  languageButton?.addEventListener("click", () => {
    applyLanguage(language === "zh" ? "en" : "zh");
  });
  applyLanguage(language);

  let theme = localStorage.getItem("vivarium-theme");
  if (theme !== "light" && theme !== "dark") {
    theme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function applyTheme(nextTheme) {
    theme = nextTheme;
    root.dataset.theme = theme;
    if (themeButton) {
      const isDark = theme === "dark";
      themeButton.textContent = isDark ? "☀" : "◐";
      themeButton.setAttribute("aria-pressed", String(isDark));
      themeButton.setAttribute(
        "aria-label",
        isDark ? "Use light appearance" : "Use dark appearance",
      );
    }
    document.querySelector('meta[name="theme-color"]')?.setAttribute(
      "content",
      theme === "dark" ? "#07172d" : "#f5f9ff",
    );
    localStorage.setItem("vivarium-theme", theme);
  }

  themeButton?.addEventListener("click", () => {
    applyTheme(theme === "dark" ? "light" : "dark");
  });
  applyTheme(theme);

  function closeMenu() {
    if (!menuButton || !menu) return;
    menu.classList.remove("open");
    menuButton.setAttribute("aria-expanded", "false");
    document.body.classList.remove("menu-open");
  }

  menuButton?.addEventListener("click", () => {
    if (!menu) return;
    const willOpen = !menu.classList.contains("open");
    menu.classList.toggle("open", willOpen);
    menuButton.setAttribute("aria-expanded", String(willOpen));
    document.body.classList.toggle("menu-open", willOpen);
  });
  menu?.querySelectorAll("a").forEach((link) => link.addEventListener("click", closeMenu));
  window.addEventListener("resize", () => {
    if (window.innerWidth > 780) closeMenu();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMenu();
  });

  const tabs = Array.from(document.querySelectorAll('[role="tab"]'));
  function activateTab(tab, moveFocus = false) {
    tabs.forEach((candidate) => {
      const selected = candidate === tab;
      candidate.setAttribute("aria-selected", String(selected));
      candidate.tabIndex = selected ? 0 : -1;
      const panel = document.getElementById(candidate.getAttribute("aria-controls"));
      if (panel) panel.hidden = !selected;
    });
    if (moveFocus) tab.focus();
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => activateTab(tab));
    tab.addEventListener("keydown", (event) => {
      let nextIndex;
      if (event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
      if (event.key === "ArrowLeft") nextIndex = (index - 1 + tabs.length) % tabs.length;
      if (event.key === "Home") nextIndex = 0;
      if (event.key === "End") nextIndex = tabs.length - 1;
      if (nextIndex === undefined) return;
      event.preventDefault();
      activateTab(tabs[nextIndex], true);
    });
  });

  let toastTimer;
  function showToast(message) {
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add("visible");
    clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toast.classList.remove("visible"), 1800);
  }

  async function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    const copied = document.execCommand("copy");
    textarea.remove();
    if (!copied) throw new Error("Copy command was rejected");
  }

  document.querySelectorAll("[data-copy]").forEach((button) => {
    button.addEventListener("click", async () => {
      const source = document.getElementById(button.dataset.copy);
      if (!source) return;
      const original = button.textContent;
      try {
        await copyText(source.textContent.trim());
        button.textContent = language === "zh" ? "已复制" : "Copied";
        showToast(language === "zh" ? "内容已复制" : "Copied to clipboard");
      } catch (error) {
        button.textContent = language === "zh" ? "复制失败" : "Copy failed";
        showToast(language === "zh" ? "请手动复制" : "Please copy manually");
      }
      window.setTimeout(() => {
        button.textContent = original;
      }, 1600);
    });
  });

  // On-site skill detail modal (no GitHub bounce).
  const skillModal = document.getElementById("skill-modal");
  if (skillModal && window.VIVARIUM_SKILLS) {
    const el = (id) => document.getElementById(id);
    const codeEl = el("skill-modal-code"), nameEl = el("skill-modal-name"),
      roleEl = el("skill-modal-role"), sumEl = el("skill-modal-summary"),
      capsEl = el("skill-modal-caps"), toolsEl = el("skill-modal-tools"),
      boundsEl = el("skill-modal-bounds"), exWrap = el("skill-modal-example-wrap"),
      exEl = el("skill-modal-example");
    let openCode = null;

    function renderSkill(code) {
      const s = window.VIVARIUM_SKILLS[code];
      if (!s) return;
      openCode = code;
      codeEl.textContent = s.code;
      nameEl.textContent = s.name;
      roleEl.textContent = language === "zh" ? s.role_zh : s.role_en;
      sumEl.textContent = language === "zh" ? s.summary_zh : s.summary_en;
      const fill = (container, items, pick) => {
        container.textContent = "";
        (items || []).forEach((item) => {
          const li = document.createElement("li");
          li.textContent = pick(item);
          container.appendChild(li);
        });
      };
      fill(capsEl, s.capabilities, (c) => (language === "zh" ? c.zh : c.en));
      fill(boundsEl, s.boundaries, (b) => (language === "zh" ? b.zh : b.en));
      toolsEl.textContent = "";
      (s.tools || []).forEach((t) => {
        const chip = document.createElement("span");
        chip.className = "skill-chip";
        chip.textContent = t;
        toolsEl.appendChild(chip);
      });
      const ex = language === "zh" ? s.example_zh : s.example_en;
      exEl.textContent = ex || "";
      exWrap.hidden = !ex;
    }

    function openSkill(code) {
      renderSkill(code);
      skillModal.hidden = false;
      requestAnimationFrame(() => skillModal.classList.add("open"));
      document.body.classList.add("menu-open");
      skillModal.querySelector(".skill-modal-close")?.focus();
    }

    function closeSkill() {
      skillModal.classList.remove("open");
      document.body.classList.remove("menu-open");
      openCode = null;
      window.setTimeout(() => { skillModal.hidden = true; }, 200);
    }

    document.querySelectorAll(".skill-card[data-skill]").forEach((card) => {
      card.addEventListener("click", () => openSkill(card.dataset.skill));
    });
    skillModal.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", closeSkill));
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !skillModal.hidden) closeSkill();
    });
    languageButton?.addEventListener("click", () => { if (openCode) renderSkill(openCode); });
  }

  // Interactive drift chart: recall fidelity vs accumulated project state.
  const driftChart = document.querySelector(".drift-chart");
  if (driftChart) {
    const svg = driftChart.querySelector("svg");
    const SVGNS = "http://www.w3.org/2000/svg";
    const X0 = 72, X1 = 604, Y_TOP = 40, Y_BOT = 320, THRESHOLD = 42, FLOOR = 8;
    const X = (s) => X0 + (s / 100) * (X1 - X0);
    const Y = (r) => Y_BOT - (r / 100) * (Y_BOT - Y_TOP);
    const recallSelf = (s) =>
      s <= THRESHOLD ? 100 : Math.max(FLOOR, 100 - ((s - THRESHOLD) / (100 - THRESHOLD)) * (100 - FLOOR));

    const grid = svg.querySelector(".drift-grid");
    const line = (x1, y1, x2, y2, cls) => {
      const el = document.createElementNS(SVGNS, "line");
      el.setAttribute("x1", x1); el.setAttribute("y1", y1);
      el.setAttribute("x2", x2); el.setAttribute("y2", y2);
      if (cls) el.setAttribute("class", cls);
      return el;
    };
    const text = (x, y, str, anchor) => {
      const el = document.createElementNS(SVGNS, "text");
      el.setAttribute("x", x); el.setAttribute("y", y);
      if (anchor) el.setAttribute("text-anchor", anchor);
      el.textContent = str;
      return el;
    };
    [0, 50, 100].forEach((r) => {
      grid.appendChild(line(X0, Y(r), X1, Y(r)));
      grid.appendChild(text(X0 - 10, Y(r) + 4, r + "%", "end"));
    });
    const th = line(X(THRESHOLD), Y_TOP - 6, X(THRESHOLD), Y_BOT, "drift-threshold");
    grid.appendChild(th);
    grid.appendChild(text(X(THRESHOLD), Y_TOP - 12, "", "middle")).setAttribute("data-th", "1");

    let dSelf = "";
    for (let s = 0; s <= 100; s += 2) dSelf += (s === 0 ? "M" : "L") + X(s).toFixed(1) + " " + Y(recallSelf(s)).toFixed(1) + " ";
    svg.querySelector(".drift-line.selfmanaged").setAttribute("d", dSelf.trim());
    svg.querySelector(".drift-line.ledger").setAttribute("d", "M" + X(0) + " " + Y(100) + " L" + X1 + " " + Y(100));

    const marker = svg.querySelector(".drift-marker");
    const dotSelf = svg.querySelector(".drift-dot.selfmanaged");
    const dotLedger = svg.querySelector(".drift-dot.ledger");
    const slider = document.getElementById("drift-scale");
    const outSelf = driftChart.querySelector('[data-value="self"]');
    const outLedger = driftChart.querySelector('[data-value="ledger"]');
    const thLabel = grid.querySelector("[data-th]");

    function updateDrift() {
      const s = Number(slider.value);
      const rs = recallSelf(s);
      marker.setAttribute("x1", X(s)); marker.setAttribute("x2", X(s));
      marker.setAttribute("y1", Y_TOP - 6); marker.setAttribute("y2", Y_BOT);
      dotSelf.setAttribute("cx", X(s)); dotSelf.setAttribute("cy", Y(rs));
      dotLedger.setAttribute("cx", X(s)); dotLedger.setAttribute("cy", Y(100));
      if (outSelf) outSelf.textContent = Math.round(rs) + "%";
      if (outLedger) outLedger.textContent = "100%";
    }
    if (thLabel) thLabel.textContent = language === "zh" ? "可携带上下文上限" : "carry limit";
    languageButton?.addEventListener("click", () => {
      if (thLabel) thLabel.textContent = language === "zh" ? "可携带上下文上限" : "carry limit";
    });
    slider?.addEventListener("input", updateDrift);
    updateDrift();
  }

  const reveals = document.querySelectorAll(".reveal");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if ("IntersectionObserver" in window && !reducedMotion) {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("visible");
          observer.unobserve(entry.target);
        });
      },
      { threshold: 0.12 },
    );
    reveals.forEach((element) => observer.observe(element));
  } else {
    reveals.forEach((element) => element.classList.add("visible"));
  }
})();

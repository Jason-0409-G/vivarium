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

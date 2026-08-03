const root = document.documentElement;
const themeToggle = document.querySelector(".theme-toggle");
const themeMeta = document.querySelector('meta[name="theme-color"]');
const productShot = document.querySelector(".product-shot");
const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");

function applyTheme(theme) {
  root.dataset.theme = theme;
  themeToggle?.setAttribute("aria-pressed", String(theme === "dark"));
  themeToggle?.setAttribute("title", theme === "dark" ? "切换到浅色主题" : "切换到深色主题");
  themeMeta?.setAttribute("content", theme === "dark" ? "#1c1c1e" : "#f5f5f7");

  const themeIcon = themeToggle?.querySelector(".theme-icon");
  if (themeIcon) themeIcon.textContent = theme === "dark" ? "☀" : "◐";

  if (productShot) {
    productShot.src = theme === "dark" ? productShot.dataset.darkSrc : productShot.dataset.lightSrc;
  }
}

applyTheme(root.dataset.theme || (systemTheme.matches ? "dark" : "light"));

themeToggle?.addEventListener("click", () => {
  const nextTheme = root.dataset.theme === "dark" ? "light" : "dark";
  applyTheme(nextTheme);
});

systemTheme.addEventListener("change", (event) => {
  applyTheme(event.matches ? "dark" : "light");
});

const siteHeader = document.querySelector(".site-header");
const updateHeader = () => siteHeader?.classList.toggle("scrolled", window.scrollY > 12);
updateHeader();
window.addEventListener("scroll", updateHeader, { passive: true });

const revealObserver = new IntersectionObserver(
  (entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("visible");
        revealObserver.unobserve(entry.target);
      }
    });
  },
  { threshold: 0.12 }
);

document.querySelectorAll(".reveal").forEach((element) => revealObserver.observe(element));

document.querySelectorAll(".copy-button").forEach((button) => {
  button.addEventListener("click", async () => {
    const text = button.dataset.copy;
    if (!text) return;

    try {
      await navigator.clipboard.writeText(text);
      button.textContent = "已复制";
      window.setTimeout(() => {
        button.textContent = "复制";
      }, 1800);
    } catch {
      button.textContent = "复制失败";
    }
  });
});

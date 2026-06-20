// Bootstrap 5.3 theme toggle


(function () {
  const root = document.documentElement;
  const toggleBtn = document.getElementById("themeToggle");
  const icon = document.getElementById("themeIcon");

  function setTheme(theme) {
    root.setAttribute("data-bs-theme", theme);
    localStorage.setItem("theme", theme);

    if (icon) {
      icon.className = theme === "dark" ? "bi bi-sun" : "bi bi-moon-stars";
    }
  }

  

  document.addEventListener("DOMContentLoaded", init);
})();

